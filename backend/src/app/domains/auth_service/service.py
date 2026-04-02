from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.domains.auth_service.browser_login import (
    BrowserLoginAdapter,
    BrowserLoginFailure,
    normalize_auth_mode,
)
from app.domains.auth_service.crypto import CredentialCrypto, LocalCredentialCrypto
from app.domains.auth_service.schemas import (
    AuthRefreshResult,
    BrowserLoginResult,
    DecryptedSystemCredentials,
)
from app.infrastructure.db.models.systems import AuthState, System, SystemCredential
from app.shared.enums import AuthStateStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuthService:
    def __init__(
        self,
        *,
        session: Session | AsyncSession,
        crypto: CredentialCrypto | None = None,
        browser_login: BrowserLoginAdapter,
    ) -> None:
        self.session = session
        self.crypto = crypto or LocalCredentialCrypto()
        self.browser_login = browser_login

    async def refresh_auth_state(self, *, system_id: UUID) -> AuthRefreshResult:
        system = await self._get(System, system_id)
        if system is None:
            return AuthRefreshResult(
                system_id=system_id,
                status="failed",
                message="system not found",
            )

        try:
            credentials = await self._load_credentials(system_id=system_id)
            if credentials is None:
                return AuthRefreshResult(
                    system_id=system_id,
                    status="failed",
                    message="system credentials not found",
                )
            decrypted = self._decrypt_credentials(credentials)
            auth_mode = normalize_auth_mode(decrypted.auth_type)
            if auth_mode == "sms_captcha":
                return AuthRefreshResult(
                    system_id=system.id,
                    status="failed",
                    message="not_implemented",
                )
            login_result = await self.browser_login.login(
                login_url=decrypted.login_url,
                username=decrypted.username,
                password=decrypted.password,
                auth_type=auth_mode,
                selectors=decrypted.selectors,
            )
            auth_state = self._build_auth_state(
                system_id=system.id,
                credentials=credentials,
                login_result=login_result,
            )
        except BrowserLoginFailure as exc:
            return AuthRefreshResult(
                system_id=system.id,
                status="retryable_failed" if exc.retryable else "failed",
                message=str(exc),
            )
        except ValueError as exc:
            return AuthRefreshResult(
                system_id=system.id,
                status="failed",
                message=str(exc),
            )

        self.session.add(auth_state)
        await self._commit()
        await self._refresh(auth_state)

        return AuthRefreshResult(
            system_id=system.id,
            status="success",
            auth_state_id=auth_state.id,
            validated_at=auth_state.validated_at,
        )

    def _decrypt_credentials(
        self,
        credentials: SystemCredential,
    ) -> DecryptedSystemCredentials:
        return DecryptedSystemCredentials(
            system_id=credentials.system_id,
            login_url=credentials.login_url,
            username=self.crypto.decrypt(
                credentials.login_username_encrypted,
                secret_ref=credentials.secret_ref,
            ),
            password=self.crypto.decrypt(
                credentials.login_password_encrypted,
                secret_ref=credentials.secret_ref,
            ),
            auth_type=credentials.login_auth_type,
            selectors=credentials.login_selectors,
            secret_ref=credentials.secret_ref,
        )

    def _build_auth_state(
        self,
        *,
        system_id: UUID,
        credentials: SystemCredential,
        login_result: BrowserLoginResult,
    ) -> AuthState:
        storage_state = login_result.storage_state
        if not self._is_storage_state_valid(storage_state):
            raise ValueError("auth_state_empty")

        validated_at = utcnow()
        cookies = cast(list[dict[str, object]], storage_state.get("cookies", []))
        local_storage = self._extract_local_storage(storage_state)

        return AuthState(
            system_id=system_id,
            status=AuthStateStatus.VALID.value,
            storage_state=storage_state,
            cookies={"items": cookies},
            local_storage=local_storage or None,
            session_storage=None,
            token_fingerprint=self._fingerprint(storage_state),
            auth_mode=login_result.auth_mode or credentials.login_auth_type,
            is_valid=True,
            validated_at=validated_at,
            expires_at=login_result.expires_at or self._expires_at_from_cookies(cookies),
        )

    def _extract_local_storage(
        self,
        storage_state: dict[str, object],
    ) -> dict[str, object]:
        origins = cast(list[dict[str, object]], storage_state.get("origins", []))
        extracted: dict[str, object] = {}
        for item in origins:
            origin = item.get("origin")
            if not isinstance(origin, str):
                continue
            local_items = cast(list[dict[str, object]], item.get("localStorage", []))
            extracted[origin] = {
                entry["name"]: entry["value"]
                for entry in local_items
                if "name" in entry and "value" in entry
            }
        return extracted

    def _expires_at_from_cookies(
        self,
        cookies: list[dict[str, object]],
    ) -> datetime | None:
        timestamps: list[datetime] = []
        for cookie in cookies:
            expires = cookie.get("expires")
            if not isinstance(expires, (int, float)) or expires <= 0:
                continue
            timestamps.append(datetime.fromtimestamp(expires, tz=UTC))
        return min(timestamps) if timestamps else None

    def _fingerprint(self, storage_state: dict[str, object]) -> str:
        try:
            payload = json.dumps(storage_state, sort_keys=True, separators=(",", ":"))
        except TypeError as exc:
            raise ValueError("captured auth state must be JSON serializable") from exc
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _is_storage_state_valid(self, storage_state: dict[str, object]) -> bool:
        cookies = cast(list[dict[str, object]], storage_state.get("cookies", []))
        if any(
            isinstance(cookie.get("name"), str)
            and cookie.get("name")
            and isinstance(cookie.get("value"), str)
            for cookie in cookies
        ):
            return True

        origins = cast(list[dict[str, object]], storage_state.get("origins", []))
        for item in origins:
            origin = item.get("origin")
            if not isinstance(origin, str) or not origin:
                continue
            local_items = cast(list[dict[str, object]], item.get("localStorage", []))
            if any(
                isinstance(entry.get("name"), str)
                and entry.get("name")
                and "value" in entry
                for entry in local_items
            ):
                return True
        return False

    async def _load_credentials(self, *, system_id: UUID) -> SystemCredential | None:
        statement = (
            select(SystemCredential)
            .where(SystemCredential.system_id == system_id)
        )
        credentials = await self._exec_all(statement)
        if not credentials:
            return None
        if len(credentials) > 1:
            raise ValueError("multiple system credentials found")
        return credentials[0]

    async def _exec_first(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.execute(statement)
            return result.scalars().first()
        return self.session.exec(statement).first()

    async def _exec_all(self, statement):
        if isinstance(self.session, AsyncSession):
            result = await self.session.execute(statement)
            return list(result.scalars().all())
        return list(self.session.exec(statement).all())

    async def _get(self, model, value):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, value)
        return self.session.get(model, value)

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()

    async def _refresh(self, model) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.refresh(model)
            return
        self.session.refresh(model)
