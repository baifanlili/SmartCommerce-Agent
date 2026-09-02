import sqlite3

import pytest

from smart_commerce.core.config import Settings
from smart_commerce.models.schemas import AdminLLMConfigWrite
from smart_commerce.services.runtime_config import (
    RuntimeConfigConflictError,
    RuntimeConfigEncryptionError,
    RuntimeLLMConfigStore,
)

TEST_ENCRYPTION_KEY = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXowMTIzNDU="


def _settings(tmp_path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "development",
        "llm_provider": "mock",
        "runtime_config_db_path": str(tmp_path / "runtime-config.sqlite3"),
        "runtime_config_encryption_key": TEST_ENCRYPTION_KEY,
    }
    values.update(overrides)
    return Settings(**values)


def _write(**overrides: object) -> AdminLLMConfigWrite:
    values: dict[str, object] = {
        "provider": "deepseek",
        "api_key": "persisted-secret-key",
        "model": "deepseekflash",
        "base_url": "https://api.deepseek.com/v1",
        "api_mode": "chat",
        "timeout_seconds": 30,
        "max_retries": 2,
        "expected_version": 1,
    }
    values.update(overrides)
    return AdminLLMConfigWrite(**values)


def test_store_starts_with_default_mock_config(tmp_path) -> None:
    store = RuntimeLLMConfigStore(_settings(tmp_path))

    view = store.view()

    assert view.provider == "mock"
    assert view.api_mode == "chat"
    assert view.api_key_configured is False
    assert view.is_active is True
    assert view.draft_version == 1
    assert view.active_version == 1


def test_save_draft_keeps_active_and_increments_draft_version(tmp_path) -> None:
    store = RuntimeLLMConfigStore(_settings(tmp_path))

    saved = store.save_draft(_write(), expected_version=1)

    assert saved.provider == "deepseek"
    assert saved.draft_version == 2
    assert saved.active_version == 1
    assert saved.is_active is False


def test_store_restores_draft_and_active_after_rebuild(tmp_path) -> None:
    settings = _settings(tmp_path)
    store = RuntimeLLMConfigStore(settings)
    saved = store.save_draft(
        _write(
            model="deepseek-chat",
            base_url="https://example.test/v1",
            api_mode="responses",
            timeout_seconds=15,
            max_retries=1,
        ),
        expected_version=1,
    )
    store.enable_draft(saved.active_version)

    rebuilt = RuntimeLLMConfigStore(settings)
    view = rebuilt.view()

    assert view.provider == "deepseek"
    assert view.model == "deepseek-chat"
    assert view.base_url == "https://example.test/v1"
    assert view.api_mode == "responses"
    assert view.timeout_seconds == 15
    assert view.max_retries == 1
    assert view.is_active is True
    assert view.draft_version == 2
    assert view.active_version == 2
    assert rebuilt.active.api_key == "persisted-secret-key"


def test_api_key_is_encrypted_at_rest(tmp_path) -> None:
    store = RuntimeLLMConfigStore(_settings(tmp_path))
    store.save_draft(_write(api_key="plain-secret-key"), expected_version=1)

    with sqlite3.connect(str(tmp_path / "runtime-config.sqlite3")) as conn:
        stored = "\n".join(row[0] for row in conn.execute("SELECT config_json FROM runtime_llm_config"))

    assert "plain-secret-key" not in stored
    assert "gAAAAA" in stored


def test_save_draft_cas_conflict_reports_current_version(tmp_path) -> None:
    store = RuntimeLLMConfigStore(_settings(tmp_path))
    store.save_draft(_write(), expected_version=1)

    with pytest.raises(RuntimeConfigConflictError) as exc_info:
        store.save_draft(_write(model="stale-model"), expected_version=1)

    assert exc_info.value.current_version == 2


def test_enable_draft_cas_conflict_reports_current_version(tmp_path) -> None:
    store = RuntimeLLMConfigStore(_settings(tmp_path))
    store.save_draft(_write(), expected_version=1)
    store.enable_draft(expected_version=1)

    with pytest.raises(RuntimeConfigConflictError) as exc_info:
        store.enable_draft(expected_version=1)

    assert exc_info.value.current_version == 2


def test_enable_persists_active_across_restart(tmp_path) -> None:
    settings = _settings(tmp_path)
    store = RuntimeLLMConfigStore(settings)
    store.save_draft(_write(), expected_version=1)
    store.enable_draft(expected_version=1)

    rebuilt = RuntimeLLMConfigStore(settings)

    assert rebuilt.active.provider == "deepseek"
    assert rebuilt.active.api_key == "persisted-secret-key"
    assert rebuilt.view().is_active is True


def test_production_environment_requires_encryption_key(tmp_path) -> None:
    settings = _settings(tmp_path, environment="production", runtime_config_encryption_key=None)

    with pytest.raises(RuntimeConfigEncryptionError):
        RuntimeLLMConfigStore(settings)


def test_invalid_encryption_key_is_rejected(tmp_path) -> None:
    settings = _settings(tmp_path, runtime_config_encryption_key="not-a-valid-fernet-key")

    with pytest.raises(RuntimeConfigEncryptionError):
        RuntimeLLMConfigStore(settings)
