from __future__ import annotations

import base64
from typing import Protocol


class CredentialCrypto(Protocol):
    def decrypt(self, value: str, *, secret_ref: str | None = None) -> str: ...


class LocalCredentialCrypto:
    """Deterministic local decryptor for the initial runtime path.

    Supports a strict `enc-b64:` envelope and plain `enc:` fixture values.
    """

    def decrypt(self, value: str, *, secret_ref: str | None = None) -> str:
        del secret_ref
        if value.startswith("enc-b64:"):
            payload = value.removeprefix("enc-b64:")
            padded = payload + "=" * (-len(payload) % 4)
            return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")

        if not value.startswith("enc:"):
            return value

        return value.removeprefix("enc:")
