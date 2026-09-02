from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Product(BaseModel):
    id: int
    name: str
    category: str
    brand: str
    price: float
    rating: float
    review_count: int
    tags: list[str]
    highlights: list[str]
    description: str


class AgentStep(BaseModel):
    agent: str
    label: str
    status: Literal["completed", "running"] = "completed"


class ShoppingFilters(BaseModel):
    max_price: float | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    keywords: list[str] = Field(default_factory=list, max_length=8)


class ShoppingIntent(BaseModel):
    name: Literal["product_recommendation"] = "product_recommendation"
    raw_message: str = Field(min_length=1, max_length=2000)
    filters: ShoppingFilters


class ProductSearchResult(BaseModel):
    intent: ShoppingIntent
    products: list[Product]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    intent: ShoppingIntent
    recommendations: list[Product]
    steps: list[AgentStep]
    mode: Literal["mock", "llm"] = "mock"


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ApiErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    trace_id: str | None = None
    details: list[ErrorDetail] = Field(default_factory=list)


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody


class AdminLLMConfigWrite(BaseModel):
    provider: Literal["mock", "deepseek"] = "mock"
    api_key: str | None = Field(default=None, max_length=500)
    model: str = Field(default="deepseekflash", min_length=1, max_length=100)
    base_url: str = Field(default="https://api.deepseek.com/v1", min_length=1, max_length=500)
    api_mode: Literal["chat", "responses"] = "chat"
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    expected_version: int = Field(ge=0)


class AdminLLMConfigEnable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)


class AdminLLMConfigView(BaseModel):
    provider: Literal["mock", "deepseek"]
    api_mode: Literal["chat", "responses"]
    model: str
    base_url: str
    timeout_seconds: float
    max_retries: int
    api_key_configured: bool
    api_key_masked: str | None = None
    is_active: bool
    draft_version: int
    active_version: int


class AdminConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    mode: Literal["mock", "llm"]
