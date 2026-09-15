"""Fail-closed public-repository safety scanner.

The sensitive denylist is stored only as SHA-256 digests so the prohibited
identifiers themselves never appear in the public Git history.
"""
from __future__ import annotations
import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HASH_GROUPS = {7: ['492ed04cd0f7e65de6e31f86e849a1034ec7fc0759087d9862375d9a8f1cc967', 'f17f6b658c4b6feb54250a4266ee642d39b6ca2e2fbc7714a6dc36ae6e6b7c9a'], 4: ['bbb87cb21e7fedae11866aa8b707eccdbe86913c455aa0aa96cf7777a375b89d', 'cb85d8f867d605d33f6f3a09ce5597eecd699aa327629f547924d8948a87748b', 'a6985f5071e697aea937e03a3512635fda9af284812ab44da5fe0c98896347d2', '972e94d8c0aa05a7a15a0d5ed33e0c276883e91d4d39115ed6ee991ff87faf72'], 6: ['3757685a54084dd8e44986ef1124721187d1bd9604ecd6a7d12a74a7a898ccd3', 'a40cfc43a2228d5224cf2d096a061a7f566b14d54eac7028a8e67a804b4f2421', '3dcc3eb0414c5bfd2021a7d2228dfff4f828da2ade001b0e75bd65f29aef8f74', 'b168a764679b9dfe566de8d8dd76a26ce2405351136d441a61fa45dbbff49027', '4566aea27853fb03fb02586eed8bbfb61a95a920aa1e1c8203cb959670cc59e2', 'f51d6b8311bb16ccd640791c1bf22e510e695beea2e0c959f7752dedb8e8951e', '467dda4df29b3ad6df89688c711b38cbed4889e2731551ebfe527f7d9d6f0574'], 10: ['f36adbd9c480d09fd07c3a829afebee81566888eb86eb25be909ea058b0ef38c', 'f830720f3e3bed7436b244a9c9b13c0e778c777ff84b72d4c06d6f9b2f1ae455'], 9: ['434e6df1cc7c2c58bb2914858f972a98dfe7aedff31f7c57babd52de737add31'], 8: ['f4437c808a6e599166a7dde1ba369c0aa9f9fbf56fe174dba19b84e6061128a6', '06c097b6dfe71b0fdb27efe6728053a4c96deb15caa8e4b212086cc966b35d7a', '70ef838ec62b2fb85a924c01cafcabc003107b526906332206c3d99cd7378885'], 3: ['39f9f47377e8f6e8c98bd510fe8a69081770050a071d31bf821220f6e887221e']}
TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".csv", ".html", ".yml", ".yaml", ".js", ".css",
    ".sh", ".txt", ".toml", ".ini", ".service", ".conf", ".example", ""
}
FORBIDDEN_BINARY_SUFFIXES = {
    ".xlsx", ".xls", ".xlsm", ".db", ".sqlite", ".sqlite3", ".pickle", ".pkl", ".parquet"
}
EMAIL_RE = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LOCAL_PATH_PATTERNS = (
    re.compile(rb"/home/[^/\s]+/"),
    re.compile(rb"/Users/[^/\s]+/"),
    re.compile(rb"[A-Za-z]:\\\\Users\\\\[^\\\s]+\\\\"),
)

SECRET_PATTERNS = (
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"sk-[A-Za-z0-9]{20,}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

ALLOW_EMAILS = {b"noreply@users.noreply.github.com"}


def _contains_hashed_term(data: bytes) -> bool:
    low = data.lower()
    for length, digests in HASH_GROUPS.items():
        if len(low) < length:
            continue
        target = set(digests)
        for i in range(0, len(low) - length + 1):
            if hashlib.sha256(low[i:i+length]).hexdigest() in target:
                return True
    return False


def main() -> int:
    failures = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        rel_bytes = rel.encode("utf-8", errors="ignore")
        if _contains_hashed_term(rel_bytes):
            failures.append(f"forbidden identifier in path: {rel}")
        if path.suffix.lower() in FORBIDDEN_BINARY_SUFFIXES:
            failures.append(f"forbidden binary/data artifact: {rel}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        data = path.read_bytes()
        if _contains_hashed_term(data):
            failures.append(f"forbidden identifier in content: {rel}")
        for email in EMAIL_RE.findall(data):
            if email.lower() not in ALLOW_EMAILS:
                failures.append(f"email-like identifier in {rel}")
                break
        if rel != "tools/public_safety_scan.py" and any(p.search(data) for p in LOCAL_PATH_PATTERNS):
            failures.append(f"local user path in {rel}")
        if any(p.search(data) for p in SECRET_PATTERNS):
            failures.append(f"secret-like token in {rel}")
    if failures:
        print("\n".join(sorted(set(failures))))
        return 1
    print("PUBLIC_REPOSITORY_SAFETY_SCAN_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
