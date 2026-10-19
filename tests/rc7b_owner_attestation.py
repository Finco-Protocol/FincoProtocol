"""RC-7B Gate R: verification of a Financial Owner attestation made with an OpenSSH signature (``ssh-keygen -Y sign``, format ``sshsig``).

Why this exists. A committed JSON record that says ``"status": "SIGNED"`` and names a person is only text: anyone able to write the repository
(including the implementation agent) could produce it. Authority must come from something the implementation agent cannot create: a signature
made with a private key that only the human Financial Owner holds, over the exact content being authorized.

This module is deliberately small, dependency-free (pure Python, hashlib only) and does exactly one thing: decide whether an armoured OpenSSH
signature is a valid ``ssh-ed25519`` signature, in a given namespace, by a given public key, over given bytes. It decides nothing about who the key
belongs to; that binding (reviewed registry + the owner's currently registered GitHub signing keys) lives in ``rc7b_quarterly_candidate_authority``.
Only Ed25519 is accepted; every other key type, hash, version or malformed encoding is rejected. It never raises for hostile input.

The Ed25519 arithmetic follows the RFC 8032 reference algorithm and is checked against the RFC test vectors and, when available, against
``ssh-keygen`` and ``cryptography`` in ``tests/test_rc7b_gate_r_authorization.py``.
"""
from __future__ import annotations

import base64
import hashlib
import re
import struct

# ── Ed25519 (RFC 8032) ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)
_ZERO = (0, 1, 1, 0)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p):
    q = _ZERO
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _compress(p) -> bytes:
    zinv = pow(p[2], _P - 2, _P)
    x, y = p[0] * zinv % _P, p[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _expand(seed: bytes):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed: bytes) -> bytes:
    return _compress(_mul(_expand(seed)[0], _G))


def sign(seed: bytes, message: bytes) -> bytes:
    a, prefix = _expand(seed)
    pub = _compress(_mul(a, _G))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _L
    r_enc = _compress(_mul(r, _G))
    h = int.from_bytes(hashlib.sha512(r_enc + pub + message).digest(), "little") % _L
    return r_enc + int.to_bytes((r + h * a) % _L, 32, "little")


def verify(pub: bytes, message: bytes, signature: bytes) -> bool:
    try:
        if len(pub) != 32 or len(signature) != 64:
            return False
        a_pt, r_pt = _decompress(pub), _decompress(signature[:32])
        if a_pt is None or r_pt is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= _L:
            return False
        h = int.from_bytes(hashlib.sha512(signature[:32] + pub + message).digest(), "little") % _L
        return _equal(_mul(s, _G), _add(r_pt, _mul(h, a_pt)))
    except (ValueError, TypeError, ZeroDivisionError):
        return False


# ── OpenSSH wire formats ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
KEY_TYPE = b"ssh-ed25519"
_MAGIC = b"SSHSIG"
_ARMOR_RE = re.compile(r"\A-----BEGIN SSH SIGNATURE-----\s*([A-Za-z0-9+/=\s]+?)\s*-----END SSH SIGNATURE-----\s*\Z")
_KEY_LINE_RE = re.compile(r"\Assh-ed25519 ([A-Za-z0-9+/]+={0,2})(?: [^\r\n]*)?\Z")


def _string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError("truncated")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def string(self) -> bytes:
        return self.take(self.u32())

    def done(self) -> bool:
        return self.pos == len(self.data)


def public_key_from_line(line) -> bytes | None:
    """The 32-byte Ed25519 public key of a strict ``ssh-ed25519 <base64> [comment]`` line, else None."""
    if not isinstance(line, str):
        return None
    match = _KEY_LINE_RE.match(line.strip())
    if not match:
        return None
    try:
        reader = _Reader(base64.b64decode(match.group(1), validate=True))
        if reader.string() != KEY_TYPE:
            return None
        key = reader.string()
        return key if reader.done() and len(key) == 32 else None
    except (ValueError, struct.error):
        return None


def key_line(pub: bytes, comment: str = "") -> str:
    return "ssh-ed25519 " + base64.b64encode(_string(KEY_TYPE) + _string(pub)).decode("ascii") + (f" {comment}" if comment else "")


def fingerprint(line) -> str | None:
    """OpenSSH ``SHA256:...`` fingerprint of a key line (as printed by ``ssh-keygen -l``)."""
    pub = public_key_from_line(line)
    if pub is None:
        return None
    digest = hashlib.sha256(_string(KEY_TYPE) + _string(pub)).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _signed_data(namespace: bytes, hash_algorithm: bytes, message: bytes) -> bytes | None:
    hasher = {b"sha256": hashlib.sha256, b"sha512": hashlib.sha512}.get(hash_algorithm)
    if hasher is None:
        return None
    return _MAGIC + _string(namespace) + _string(b"") + _string(hash_algorithm) + _string(hasher(message).digest())


def make_signature(seed: bytes, message: bytes, namespace: str, hash_algorithm: str = "sha512") -> str:
    """Armoured sshsig exactly as ``ssh-keygen -Y sign -n <namespace>`` would produce it (used by tests and by documentation only)."""
    pub = public_key(seed)
    data = _signed_data(namespace.encode(), hash_algorithm.encode(), message)
    wire_sig = _string(KEY_TYPE) + _string(sign(seed, data))
    blob = (_MAGIC + struct.pack(">I", 1) + _string(_string(KEY_TYPE) + _string(pub)) + _string(namespace.encode()) + _string(b"")
            + _string(hash_algorithm.encode()) + _string(wire_sig))
    body = base64.b64encode(blob).decode("ascii")
    lines = [body[i:i + 70] for i in range(0, len(body), 70)]
    return "-----BEGIN SSH SIGNATURE-----\n" + "\n".join(lines) + "\n-----END SSH SIGNATURE-----\n"


def verification_problems(armoured, message, namespace: str, expected_key_line) -> list[str]:
    """[] only if ``armoured`` is a valid ssh-ed25519 sshsig over ``message`` in ``namespace`` made by exactly ``expected_key_line``."""
    expected = public_key_from_line(expected_key_line)
    if expected is None:
        return ["OWNER_SIGNATURE_UNVERIFIABLE: the signing key is not a strict ssh-ed25519 public key"]
    if not isinstance(armoured, str) or not isinstance(message, (bytes, bytearray)):
        return ["OWNER_SIGNATURE_UNVERIFIABLE: signature or payload is malformed"]
    match = _ARMOR_RE.match(armoured)
    if not match:
        return ["OWNER_SIGNATURE_UNVERIFIABLE: not an armoured OpenSSH signature"]
    try:
        reader = _Reader(base64.b64decode("".join(match.group(1).split()), validate=True))
        if reader.take(6) != _MAGIC or reader.u32() != 1:
            return ["OWNER_SIGNATURE_INVALID: wrong magic or version"]
        key_blob, sig_namespace, reserved, hash_algorithm, sig_blob = (reader.string() for _ in range(5))
        if not reader.done():
            return ["OWNER_SIGNATURE_INVALID: trailing data"]
        key_reader = _Reader(key_blob)
        if key_reader.string() != KEY_TYPE:
            return ["OWNER_SIGNATURE_INVALID: only ssh-ed25519 is accepted"]
        signer = key_reader.string()
        if not key_reader.done() or signer != expected:
            return ["OWNER_SIGNATURE_INVALID: signed by a different key than the registered Financial Owner key"]
        if sig_namespace != namespace.encode() or reserved != b"":
            return ["OWNER_SIGNATURE_INVALID: wrong namespace (a signature for another purpose cannot be replayed here)"]
        sig_reader = _Reader(sig_blob)
        if sig_reader.string() != KEY_TYPE:
            return ["OWNER_SIGNATURE_INVALID: signature algorithm mismatch"]
        raw = sig_reader.string()
        if not sig_reader.done():
            return ["OWNER_SIGNATURE_INVALID: trailing signature data"]
        data = _signed_data(sig_namespace, hash_algorithm, bytes(message))
        if data is None:
            return ["OWNER_SIGNATURE_INVALID: unsupported hash algorithm"]
        return [] if verify(signer, data, raw) else ["OWNER_SIGNATURE_INVALID: the signature does not verify over this exact payload"]
    except (ValueError, struct.error):
        return ["OWNER_SIGNATURE_UNVERIFIABLE: malformed signature encoding"]
