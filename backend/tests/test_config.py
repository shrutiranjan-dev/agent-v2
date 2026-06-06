import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings


def test_settings_loads_legacy_env_names(monkeypatch) -> None:
    monkeypatch.setenv("AP_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/app")
    monkeypatch.setenv("AP_REDIS_URL", "redis://redis:6379/4")
    monkeypatch.setenv("AP_OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("AP_CONTEXT_CHAR_BUDGET", "12000")
    monkeypatch.setenv("AP_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

    settings = Settings(_env_file=None)

    assert settings.database.url == "postgresql+asyncpg://u:p@db:5432/app"
    assert settings.redis.url == "redis://redis:6379/4"
    assert settings.ollama.base_url == "http://host.docker.internal:11434"
    assert settings.runtime.context_char_budget == 12000
    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_production_defaults_are_rejected(monkeypatch) -> None:
    monkeypatch.setenv("AP_ENV", "production")
    monkeypatch.delenv("AP_SECURITY_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    assert "Invalid production configuration" in str(exc.value)
    assert "security.secret_key" in str(exc.value)


def test_workspace_root_override_flows_into_lsp_when_lsp_override_is_unset(monkeypatch) -> None:
    monkeypatch.setenv("AP_WORKSPACE_ROOT", "/tmp/workspace-root")
    monkeypatch.delenv("AP_LSP_WORKSPACE_ROOT", raising=False)

    settings = Settings(_env_file=None)

    assert settings.runtime.workspace_root == settings.lsp.workspace_root
    assert settings.lsp.workspace_root.as_posix() == "/tmp/workspace-root"
