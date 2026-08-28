import re
import secrets
from typing import TYPE_CHECKING, Literal

from fastapi import Request
from pydantic import BaseModel, Field

from smart_commerce.core.errors import ApiError

if TYPE_CHECKING:
    from smart_commerce.core.config import Settings


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ROLES = {"user", "admin", "observer"}


class IdentityContext(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    role: Literal["user", "admin", "observer"]
    scopes: tuple[str, ...] = ()
    trace_id: str = Field(min_length=1, max_length=128)


def resolve_identity(request: Request, settings: "Settings") -> IdentityContext:
    trace_id = request.state.trace_id
    if settings.environment.lower() == "development" and settings.identity_mode == "development":
        return IdentityContext(
            user_id="anonymous",
            tenant_id="development",
            role="user",
            scopes=("agent:chat",),
            trace_id=trace_id,
        )

    configured_token = settings.identity_gateway_token
    if not configured_token:
        raise ApiError(503, "IDENTITY_AUTH_NOT_CONFIGURED", "身份网关认证尚未配置")

    supplied_token = request.headers.get("x-agent-identity-token")
    if not supplied_token or not secrets.compare_digest(supplied_token, configured_token):
        raise ApiError(401, "IDENTITY_TOKEN_INVALID", "身份网关认证失败")

    user_id = _required_identifier(request, "x-agent-user-id", "user_id")
    tenant_id = _required_identifier(request, "x-agent-tenant-id", "tenant_id")
    role = request.headers.get("x-agent-role", "").strip()
    if role not in _ROLES:
        raise ApiError(401, "IDENTITY_CONTEXT_INVALID", "身份上下文不完整或无效", [{"field": "role", "message": "角色无效"}])

    return IdentityContext(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        scopes=_parse_scopes(request.headers.get("x-agent-scopes")),
        trace_id=trace_id,
    )


def _required_identifier(request: Request, header_name: str, field_name: str) -> str:
    value = request.headers.get(header_name, "").strip()
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ApiError(
            401,
            "IDENTITY_CONTEXT_INVALID",
            "身份上下文不完整或无效",
            [{"field": field_name, "message": "必须是 1-128 位的字母、数字、点、下划线或连字符"}],
        )
    return value


def _parse_scopes(raw_scopes: str | None) -> tuple[str, ...]:
    if raw_scopes is None:
        return ()
    scopes = tuple(scope.strip() for scope in raw_scopes.split(","))
    if not scopes or any(not scope or len(scope) > 100 for scope in scopes):
        raise ApiError(401, "IDENTITY_CONTEXT_INVALID", "身份上下文不完整或无效", [{"field": "scopes", "message": "权限范围格式无效"}])
    return scopes
