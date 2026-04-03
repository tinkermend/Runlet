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
