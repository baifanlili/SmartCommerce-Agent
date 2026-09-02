import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from smart_commerce.core.config import Settings
from smart_commerce.models.schemas import AdminLLMConfigView, AdminLLMConfigWrite
from smart_commerce.services.llm_provider import LLMProvider, build_llm_provider

logger = logging.getLogger(__name__)

# 仅用于本地 development 且未配置 RUNTIME_CONFIG_ENCRYPTION_KEY 的场景；生产环境禁止使用。
_DEV_ONLY_ENCRYPTION_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="

_DRAFT_KEY = "draft"
_ACTIVE_KEY = "active"
_INITIAL_VERSION = 1


@dataclass(frozen=True)
class RuntimeLLMConfig:
    provider: str
    api_key: str | None
    model: str
    base_url: str
    api_mode: str
    timeout_seconds: float
    max_retries: int


class RuntimeConfigConflictError(Exception):
    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"配置版本已变化，当前版本为 {current_version}")


class RuntimeConfigEncryptionError(Exception):
    """加密密钥缺失、无效或无法解密已保存配置时抛出。"""


def _mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 6:
        return "******"
    return f"{api_key[:3]}...{api_key[-3:]}"


class RuntimeLLMConfigStore:
    """Persists draft and active provider config in SQLite with encrypted API keys."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db_path = Path(settings.runtime_config_db_path)
        self._fernet = self._load_fernet(settings)
        self._draft: RuntimeLLMConfig | None = None
        self._active: RuntimeLLMConfig | None = None
        self._draft_version = 0
        self._active_version = 0

    @staticmethod
    def _load_fernet(settings: Settings) -> Fernet:
        configured_key = settings.runtime_config_encryption_key
        if configured_key:
            try:
                return Fernet(configured_key.encode("ascii"))
            except (TypeError, ValueError) as exc:
                raise RuntimeConfigEncryptionError("RUNTIME_CONFIG_ENCRYPTION_KEY 不是有效的 Fernet 密钥") from exc
        if settings.environment == "development":
            return Fernet(_DEV_ONLY_ENCRYPTION_KEY.encode("ascii"))
        raise RuntimeConfigEncryptionError("非 development 环境必须配置 RUNTIME_CONFIG_ENCRYPTION_KEY")

    @property
    def active(self) -> RuntimeLLMConfig:
        self._ensure_loaded()
        assert self._active is not None
        return self._active

    @property
    def draft(self) -> RuntimeLLMConfig:
        self._ensure_loaded()
        assert self._draft is not None
        return self._draft

    def save_draft(self, payload: AdminLLMConfigWrite, expected_version: int) -> AdminLLMConfigView:
        self._ensure_loaded()
        assert self._draft is not None
        candidate = self._from_payload(payload, self._draft)
        next_version = expected_version + 1
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE runtime_llm_config SET version=?, config_json=? WHERE key=? AND version=?",
                (next_version, self._serialize(candidate), _DRAFT_KEY, expected_version),
            )
            if cursor.rowcount == 0:
                raise RuntimeConfigConflictError(self._current_version(conn, _DRAFT_KEY))
            conn.commit()
        self._draft = candidate
        self._draft_version = next_version
        return self.view()

    def enable_draft(self, expected_version: int) -> AdminLLMConfigView:
        self._ensure_loaded()
        assert self._draft is not None
        next_version = expected_version + 1
        with self._connect() as conn:
            draft_row = conn.execute(
                "SELECT version, config_json FROM runtime_llm_config WHERE key=?",
                (_DRAFT_KEY,),
            ).fetchone()
            if draft_row is None:
                raise RuntimeConfigConflictError(self._current_version(conn, _ACTIVE_KEY))
            cursor = conn.execute(
                "UPDATE runtime_llm_config SET version=?, config_json=? WHERE key=? AND version=?",
                (next_version, draft_row["config_json"], _ACTIVE_KEY, expected_version),
            )
            if cursor.rowcount == 0:
                raise RuntimeConfigConflictError(self._current_version(conn, _ACTIVE_KEY))
            conn.commit()
        self._active = self._draft
        self._active_version = next_version
        return self.view()

    def build_provider(self, config: RuntimeLLMConfig | None = None) -> LLMProvider:
        selected = config or self.active
        return build_llm_provider(
            provider=selected.provider,
            api_key=selected.api_key,
            model=selected.model,
            base_url=selected.base_url,
            api_mode=selected.api_mode,  # type: ignore[arg-type]
            timeout_seconds=selected.timeout_seconds,
            max_retries=selected.max_retries,
        )

    def config_for_test(self, payload: AdminLLMConfigWrite) -> RuntimeLLMConfig:
        self._ensure_loaded()
        assert self._draft is not None
        return self._from_payload(payload, self._draft)

    def view(self) -> AdminLLMConfigView:
        self._ensure_loaded()
        assert self._draft is not None
        assert self._active is not None
        config = self._draft
        return AdminLLMConfigView(
            provider=config.provider,
            api_mode=config.api_mode,
            model=config.model,
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            api_key_configured=bool(config.api_key),
            api_key_masked=_mask_api_key(config.api_key),
            is_active=config == self._active,
            draft_version=self._draft_version,
            active_version=self._active_version,
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_loaded(self) -> None:
        if self._draft is not None and self._active is not None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        initial = self._from_settings(self._settings)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_llm_config (
                    key TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    config_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO runtime_llm_config (key, version, config_json) VALUES (?, ?, ?)",
                (_DRAFT_KEY, _INITIAL_VERSION, self._serialize(initial)),
            )
            conn.execute(
                "INSERT OR IGNORE INTO runtime_llm_config (key, version, config_json) VALUES (?, ?, ?)",
                (_ACTIVE_KEY, _INITIAL_VERSION, self._serialize(initial)),
            )
            conn.commit()
            draft = self._read_row(conn, _DRAFT_KEY)
            active = self._read_row(conn, _ACTIVE_KEY)
            if draft is None or active is None:
                raise RuntimeConfigEncryptionError("运行期配置数据库初始化失败")
            self._draft_version, self._draft = draft
            self._active_version, self._active = active

    @staticmethod
    def _current_version(conn: sqlite3.Connection, key: str) -> int:
        row = conn.execute("SELECT version FROM runtime_llm_config WHERE key=?", (key,)).fetchone()
        return int(row["version"]) if row else 0

    def _read_row(self, conn: sqlite3.Connection, key: str) -> tuple[int, RuntimeLLMConfig] | None:
        row = conn.execute(
            "SELECT version, config_json FROM runtime_llm_config WHERE key=?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row["version"]), self._deserialize(row["config_json"])
        except InvalidToken as exc:
            raise RuntimeConfigEncryptionError("已保存的配置无法解密，请检查 RUNTIME_CONFIG_ENCRYPTION_KEY") from exc

    def _serialize(self, config: RuntimeLLMConfig) -> str:
        return json.dumps(
            {
                "provider": config.provider,
                "api_key_encrypted": self._encrypt_api_key(config.api_key),
                "model": config.model,
                "base_url": config.base_url,
                "api_mode": config.api_mode,
                "timeout_seconds": config.timeout_seconds,
                "max_retries": config.max_retries,
            },
            ensure_ascii=False,
        )

    def _deserialize(self, raw: str) -> RuntimeLLMConfig:
        data = json.loads(raw)
        return RuntimeLLMConfig(
            provider=data["provider"],
            api_key=self._decrypt_api_key(data.get("api_key_encrypted")),
            model=data["model"],
            base_url=data["base_url"],
            api_mode=data["api_mode"],
            timeout_seconds=float(data["timeout_seconds"]),
            max_retries=int(data["max_retries"]),
        )

    def _encrypt_api_key(self, api_key: str | None) -> str | None:
        if not api_key:
            return None
        return self._fernet.encrypt(api_key.encode("utf-8")).decode("ascii")

    def _decrypt_api_key(self, token: str | None) -> str | None:
        if not token:
            return None
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")

    @staticmethod
    def _from_settings(settings: Settings) -> RuntimeLLMConfig:
        return RuntimeLLMConfig(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key,
            model=settings.llm_model or "deepseekflash",
            base_url=settings.llm_base_url,
            api_mode=settings.llm_api_mode,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    @staticmethod
    def _from_payload(payload: AdminLLMConfigWrite, current: RuntimeLLMConfig) -> RuntimeLLMConfig:
        return RuntimeLLMConfig(
            provider=payload.provider,
            api_key=current.api_key if payload.api_key is None else payload.api_key,
            model=payload.model,
            base_url=payload.base_url,
            api_mode=payload.api_mode,
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )
