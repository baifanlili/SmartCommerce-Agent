from dataclasses import dataclass

from smart_commerce.core.config import Settings
from smart_commerce.models.schemas import AdminLLMConfigView, AdminLLMConfigWrite
from smart_commerce.services.llm_provider import LLMProvider, build_llm_provider


@dataclass(frozen=True)
class RuntimeLLMConfig:
    provider: str
    api_key: str | None
    model: str
    base_url: str
    api_mode: str
    timeout_seconds: float
    max_retries: int


def _mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 6:
        return "******"
    return f"{api_key[:3]}...{api_key[-3:]}"


class RuntimeLLMConfigStore:
    """Keeps a draft and active provider config until persistent secret storage exists."""

    def __init__(self, settings: Settings) -> None:
        initial = RuntimeLLMConfig(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key,
            model=settings.llm_model or "deepseekflash",
            base_url=settings.llm_base_url,
            api_mode=settings.llm_api_mode,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        self._active = initial
        self._draft = initial

    @property
    def active(self) -> RuntimeLLMConfig:
        return self._active

    @property
    def draft(self) -> RuntimeLLMConfig:
        return self._draft

    def save_draft(self, payload: AdminLLMConfigWrite) -> AdminLLMConfigView:
        self._draft = self._from_payload(payload, self._draft)
        return self.view()

    def enable_draft(self) -> AdminLLMConfigView:
        self._active = self._draft
        return self.view()

    def build_provider(self, config: RuntimeLLMConfig | None = None) -> LLMProvider:
        selected = config or self._active
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
        return self._from_payload(payload, self._draft)

    def view(self) -> AdminLLMConfigView:
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
