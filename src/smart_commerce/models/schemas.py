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
