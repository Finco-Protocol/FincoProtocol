"""Pure-Python EVM cryptographic primitives.

Implements:
  keccak256        — Ethereum's Keccak-256 (NOT standard SHA3-256)
  secp256k1_*      — ECDSA key generation and signature recovery on secp256k1
  eth_address_from_pubkey — derive Ethereum address from (x, y) public key

No external dependencies beyond Python stdlib.  Tested against known-good
Ethereum vectors.
"""
from __future__ import annotations

import os
import struct
from typing import NamedTuple


# ── Keccak-256 ───────────────────────────────────────────────────────────────
# Ethereum uses the original Keccak team's specification, which differs from
# NIST SHA3 only in the domain-separation byte (0x01 vs 0x06).
# Parameters: rate=1088, capacity=512 → output=256 bits.

_KECCAK_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

_KECCAK_RHO = [
    1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14, 27, 41, 56, 8, 25, 43, 62,
    18, 39, 61, 20, 44,
]

_KECCAK_PI = [
    10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4, 15, 23, 19, 13, 12, 2, 20,
    14, 22, 9, 6, 1,
]

_MASK64 = (1 << 64) - 1


def _rot64(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _MASK64


def _keccak_f1600(state: list[int]) -> list[int]:
    """Apply Keccak-f[1600] permutation to a 25-word (64-bit) state."""
    for rc in _KECCAK_RC:
        # Theta
        C = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
             for x in range(5)]
        D = [C[(x - 1) % 5] ^ _rot64(C[(x + 1) % 5], 1) for x in range(5)]
        state = [state[i] ^ D[i % 5] for i in range(25)]

        # Rho and Pi combined
        B = [0] * 25
        B[0] = state[0]
        x, y = 1, 0
        for i in range(24):
            idx = x + 5 * y
            B[_KECCAK_PI[i]] = _rot64(state[idx], _KECCAK_RHO[i])
            x, y = y, (2 * x + 3 * y) % 5

        # Chi
        state = [
            B[i] ^ ((~B[(i % 5 + 1) % 5 + (i // 5) * 5]) & B[(i % 5 + 2) % 5 + (i // 5) * 5])
            for i in range(25)
        ]

        # Iota
        state[0] ^= rc

    return state


def keccak256(data: bytes) -> bytes:
    """Compute Ethereum's Keccak-256 hash."""
    # Rate = 1088 bits = 136 bytes; capacity = 512 bits
    rate_bytes = 136

    # Padding: multi-rate padding with domain byte 0x01 (Keccak, not SHA3's 0x06)
    padded = bytearray(data)
    padded.append(0x01)
    # Pad to multiple of rate_bytes
    while len(padded) % rate_bytes != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    # Initialize 5x5 state of 64-bit words (all zeros)
    state: list[int] = [0] * 25

    # Absorb
    offset = 0
    while offset < len(padded):
        block = padded[offset:offset + rate_bytes]
        # XOR block into state (rate_bytes / 8 = 17 lanes)
        for i in range(17):
            lane = struct.unpack_from("<Q", block, i * 8)[0]
            state[i] ^= lane
        state = _keccak_f1600(state)
        offset += rate_bytes

    # Squeeze first 32 bytes (256 bits)
    result = bytearray()
    for i in range(4):
        result += struct.pack("<Q", state[i])
    return bytes(result)


# ── secp256k1 ────────────────────────────────────────────────────────────────

_P  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_G  = (_GX, _GY)


def _modinv(a: int, m: int) -> int:
    """Modular inverse using extended Euclidean algorithm."""
    if a == 0:
        raise ZeroDivisionError("no inverse of 0")
    lm, hm = 1, 0
    low, high = a % m, m
    while low > 1:
        ratio = high // low
        nm = hm - lm * ratio
        new = high - low * ratio
        hm, lm = lm, nm
        high, low = low, new
    return lm % m


def _point_add(P, Q):
    """Add two secp256k1 curve points."""
    if P is None:
        return Q
    if Q is None:
        return P
    px, py = P
    qx, qy = Q
    if px == qx:
        if py != qy:
            return None  # point at infinity
        # Point doubling
        lam = (3 * px * px * _modinv(2 * py, _P)) % _P
    else:
        lam = ((qy - py) * _modinv(qx - px, _P)) % _P
    rx = (lam * lam - px - qx) % _P
    ry = (lam * (px - rx) - py) % _P
    return (rx, ry)


def _point_mul(k: int, P) -> tuple[int, int] | None:
    """Scalar multiplication on secp256k1 using double-and-add."""
    result = None
    addend = P
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


# ── Key generation ───────────────────────────────────────────────────────────

class Secp256k1Keypair(NamedTuple):
    private_key: int
    public_key: tuple[int, int]


def generate_keypair() -> Secp256k1Keypair:
    """Generate a fresh secp256k1 keypair from os.urandom."""
    while True:
        raw = os.urandom(32)
        priv = int.from_bytes(raw, "big")
        if 1 <= priv < _N:
            pub = _point_mul(priv, _G)
            assert pub is not None
            return Secp256k1Keypair(private_key=priv, public_key=pub)


# ── ECDSA signing ─────────────────────────────────────────────────────────────

def _sign_hash(msg_hash: bytes, private_key: int) -> tuple[int, int, int]:
    """Sign a 32-byte hash with a secp256k1 private key.

    Returns (r, s, v) where v is 0 or 1 (the recovery id).
    """
    z = int.from_bytes(msg_hash, "big")
    while True:
        k = int.from_bytes(os.urandom(32), "big") % (_N - 1) + 1
        R = _point_mul(k, _G)
        if R is None:
            continue
        rx, ry = R
        r = rx % _N
        if r == 0:
            continue
        k_inv = _modinv(k, _N)
        s = (k_inv * (z + r * private_key)) % _N
        if s == 0:
            continue
        v = ry % 2
        return r, s, v


def sign_personal_message(message: str, private_key: int) -> str:
    """Sign an Ethereum personal_sign message (EIP-191).

    Returns the 65-byte signature as '0x' + hex.
    """
    prefix = f"\x19Ethereum Signed Message:\n{len(message.encode())}"
    full = (prefix + message).encode()
    msg_hash = keccak256(full)
    r, s, v = _sign_hash(msg_hash, private_key)
    # Ethereum v is 27 or 28
    eth_v = v + 27
    sig_bytes = r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([eth_v])
    return "0x" + sig_bytes.hex()


# ── ECDSA recovery ────────────────────────────────────────────────────────────

def _recover_public_key(msg_hash: bytes, r: int, s: int, v: int) -> tuple[int, int] | None:
    """Recover the secp256k1 public key from an ECDSA signature.

    v should be 0 or 1 (recovery id).
    """
    x = r  # simplified: we only check x = r (not r + N)
    if x >= _P:
        return None

    # Compute y from curve equation y^2 = x^3 + 7 (mod p)
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)  # works because p ≡ 3 (mod 4)
    if (y * y) % _P != y_sq:
        return None  # x is not on the curve
    if (y % 2) != v:
        y = _P - y

    R = (x, y)
    z = int.from_bytes(msg_hash, "big")
    r_inv = _modinv(r, _N)

    # Q = r_inv * (s * R - z * G)
    sR = _point_mul(s, R)
    zG = _point_mul(z, _G)
    if zG is None:
        return None
    neg_zG = (zG[0], (-zG[1]) % _P)
    sR_minus_zG = _point_add(sR, neg_zG)
    Q = _point_mul(r_inv, sR_minus_zG)
    return Q


def recover_eip191_signer(message: str, signature_hex: str) -> str | None:
    """Recover the Ethereum address that signed an EIP-191 personal message.

    Returns the 0x-prefixed address (lowercase) or None on failure.
    message: the raw challenge string (before EIP-191 prefix).
    signature_hex: '0x' + 130 hex chars (65 bytes: r[32] s[32] v[1]).
    """
    sig = signature_hex.strip()
    if sig.startswith("0x") or sig.startswith("0X"):
        sig = sig[2:]
    try:
        sig_bytes = bytes.fromhex(sig)
    except ValueError:
        return None
    if len(sig_bytes) != 65:
        return None

    r = int.from_bytes(sig_bytes[:32], "big")
    s = int.from_bytes(sig_bytes[32:64], "big")
    eth_v = sig_bytes[64]
    if eth_v not in (27, 28):
        # Allow raw 0/1 as well
        if eth_v in (0, 1):
            v = eth_v
        else:
            return None
    else:
        v = eth_v - 27

    prefix = f"\x19Ethereum Signed Message:\n{len(message.encode())}"
    full = (prefix + message).encode()
    msg_hash = keccak256(full)

    pub = _recover_public_key(msg_hash, r, s, v)
    if pub is None:
        return None

    return _pub_to_address(pub)


def _pub_to_address(pub: tuple[int, int]) -> str:
    """Derive Ethereum address from (x, y) public key."""
    pub_bytes = pub[0].to_bytes(32, "big") + pub[1].to_bytes(32, "big")
    addr_bytes = keccak256(pub_bytes)[-20:]
    return "0x" + addr_bytes.hex()


def private_key_to_address(private_key: int) -> str:
    """Derive Ethereum address from a private key integer."""
    pub = _point_mul(private_key, _G)
    assert pub is not None
    return _pub_to_address(pub)
