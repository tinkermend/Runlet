from __future__ import annotations

import hashlib
import hmac
import secrets

from app.config.settings import settings

_ALGO = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 260_000
_SALT_BYTES = 16


def _apply_pepper(password: str) -> str:
    if settings.password_pepper:
        return f"{password}{settings.password_pepper}"
    return password


def hash_password(password: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    salt = secrets.token_hex(_SALT_BYTES)
    payload = _apply_pepper(password).encode("utf-8")
    derived = hashlib.pbkdf2_hmac("sha256", payload, salt.encode("utf-8"), iterations)
    return f"{_ALGO}${iterations}${salt}${derived.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iterations_raw, salt, digest = password_hash.split("$", 3)
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    try:
        iterations = int(iterations_raw)
    except ValueError:
        return False

    payload = _apply_pepper(password).encode("utf-8")
    derived = hashlib.pbkdf2_hmac("sha256", payload, salt.encode("utf-8"), iterations)
    return hmac.compare_digest(derived.hex(), digest)
