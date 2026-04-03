import pytest
from pydantic import ValidationError

from app.domains.auth_service.crypto import LocalCredentialCrypto
from app.domains.control_plane.system_admin_schemas import WebSystemManifest


def test_web_system_manifest_accepts_nested_yaml_sections() -> None:
    manifest = WebSystemManifest.model_validate(
        {
            "system": {
                "code": "hotgo_test3",
                "name": "hotgo",
                "base_url": "https://hotgo.facms.cn",
                "framework_type": "react",
            },
            "credential": {
                "login_url": "https://hotgo.facms.cn/admin#/login?redirect=/dashboard",
                "username": "admin",
                "password": "123456",
                "auth_type": "image_captcha",
                "selectors": {"username": "input[name=username]"},
            },
            "auth_policy": {
                "enabled": True,
                "schedule_expr": "*/30 * * * *",
                "auth_mode": "image_captcha",
                "captcha_provider": "ddddocr",
            },
            "crawl_policy": {
                "enabled": True,
                "schedule_expr": "0 */2 * * *",
                "crawl_scope": "full",
            },
            "publish": {
                "check_goal": "table_render",
                "schedule_expr": "*/30 * * * *",
                "enabled": True,
            },
        }
    )

    assert manifest.system.code == "hotgo_test3"
    assert manifest.publish.check_goal == "table_render"


def test_local_credential_crypto_round_trips_with_env_secret() -> None:
    crypto = LocalCredentialCrypto(secret="test-secret")
    encrypted = crypto.encrypt("admin")

    assert encrypted.startswith("enc-b64:")
    assert crypto.decrypt(encrypted) == "admin"


@pytest.mark.parametrize(
    ("section", "field_name"),
    [
        ("system", "code"),
        ("system", "name"),
        ("system", "base_url"),
        ("system", "framework_type"),
        ("credential", "login_url"),
        ("credential", "username"),
        ("credential", "password"),
        ("credential", "auth_type"),
        ("auth_policy", "schedule_expr"),
        ("auth_policy", "auth_mode"),
        ("crawl_policy", "schedule_expr"),
        ("publish", "check_goal"),
        ("publish", "schedule_expr"),
    ],
)
def test_web_system_manifest_rejects_empty_required_text_fields(
    section: str,
    field_name: str,
) -> None:
    payload = {
        "system": {
            "code": "hotgo_test3",
            "name": "hotgo",
            "base_url": "https://hotgo.facms.cn",
            "framework_type": "react",
        },
        "credential": {
            "login_url": "https://hotgo.facms.cn/admin#/login?redirect=/dashboard",
            "username": "admin",
            "password": "123456",
            "auth_type": "image_captcha",
            "selectors": {"username": "input[name=username]"},
        },
        "auth_policy": {
            "enabled": True,
            "schedule_expr": "*/30 * * * *",
            "auth_mode": "image_captcha",
            "captcha_provider": "ddddocr",
        },
        "crawl_policy": {
            "enabled": True,
            "schedule_expr": "0 */2 * * *",
            "crawl_scope": "full",
        },
        "publish": {
            "check_goal": "table_render",
            "schedule_expr": "*/30 * * * *",
            "enabled": True,
        },
    }
    payload[section][field_name] = "   "

    with pytest.raises(ValidationError):
        WebSystemManifest.model_validate(payload)


def test_local_credential_crypto_decrypt_supports_legacy_enc_prefix() -> None:
    crypto = LocalCredentialCrypto(secret="test-secret")

    assert crypto.decrypt("enc:legacy-admin") == "legacy-admin"


def test_local_credential_crypto_decrypt_supports_legacy_b64_without_secret_prefix() -> None:
    crypto = LocalCredentialCrypto(secret="test-secret")

    assert crypto.decrypt("enc-b64:bGVnYWN5LWFkbWlu") == "legacy-admin"
