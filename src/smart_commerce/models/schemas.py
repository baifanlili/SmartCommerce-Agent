from typing import Literal

from pydantic import BaseModel, Field


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


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
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


class AdminConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    mode: Literal["mock", "llm"]
