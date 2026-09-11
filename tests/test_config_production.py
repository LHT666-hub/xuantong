import pytest

from app.config import Settings


def production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "debug": False,
        "database_url": "postgresql+asyncpg://user:pass@db.internal/xuantong",
        "llm_provider": "qwen",
        "llm_api_key": "test-key",
        "jwt_secret": "a" * 64,
        "api_auth_required": True,
        "rate_limit_enabled": True,
        "cors_allowed_origins": "",
        "use_medical_model": False,
        "ruomu_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_safe_production_settings_are_accepted():
    production_settings().validate_production()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite+aiosqlite:///./xuantong.db"),
        ("llm_api_key", ""),
        ("jwt_secret", "change-me-in-production"),
        ("api_auth_required", False),
        ("rate_limit_enabled", False),
        ("cors_allowed_origins", "*"),
    ],
)
def test_unsafe_production_settings_fail_closed(field, value):
    with pytest.raises(RuntimeError, match="生产配置不安全"):
        production_settings(**{field: value}).validate_production()
