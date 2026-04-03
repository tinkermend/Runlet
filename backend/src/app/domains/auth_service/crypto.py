from __future__ import annotations

import base64
from typing import Protocol

from app.config.settings import settings


class CredentialCrypto(Protocol):
    def encrypt(self, value: str, *, secret_ref: str | None = None) -> str: ...

    def decrypt(self, value: str, *, secret_ref: str | None = None) -> str: ...


class LocalCredentialCrypto:
    """Deterministic local decryptor for the initial runtime path.

    Supports deterministic `enc-b64:` values and plain `enc:` fixture values.
    """

    def __init__(self, secret: str | None = None) -> None:
        self.secret = secret or settings.credential_crypto_secret

    def encrypt(self, value: str, *, secret_ref: str | None = None) -> str:
        del secret_ref
        payload = f"{self.secret}:{value}".encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")
        return f"enc-b64:{encoded}"

    def decrypt(self, value: str, *, secret_ref: str | None = None) -> str:
        del secret_ref
        if value.startswith("enc-b64:"):
            payload = value.removeprefix("enc-b64:")
            padded = payload + "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
            prefix = f"{self.secret}:"
            if decoded.startswith(prefix):
                return decoded.removeprefix(prefix)
            return decoded

        if not value.startswith("enc:"):
            return value

        return value.removeprefix("enc:")
