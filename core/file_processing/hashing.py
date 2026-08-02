"""Hash helpers for processed file bytes."""

from hashlib import sha256


def sha256_hex(data: bytes) -> str:
    return sha256(data).hexdigest()
