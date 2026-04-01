from __future__ import annotations

import base64
from typing import Protocol


class CredentialCrypto(Protocol):
    def decrypt(self, value: str, *, secret_ref: str | None = None) -> str: ...


class LocalCredentialCrypto:
    """Deterministic local decryptor for the initial runtime path.

    Supports `enc:<base64>` tokens and falls back to stripping the prefix for
    fixtures or already-decrypted local values.
    """

    def decrypt(self, value: str, *, secret_ref: str | None = None) -> str:
        del secret_ref
        if not value.startswith("enc:"):
            return value

        payload = value.removeprefix("enc:")
        padded = payload + "=" * (-len(payload) % 4)
        try:
            return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        except Exception:
            return payload
