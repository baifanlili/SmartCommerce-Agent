import json
import logging
from collections import defaultdict
from urllib.parse import quote

from redis.asyncio import Redis

from smart_commerce.core.identity import IdentityContext

logger = logging.getLogger(__name__)


class SessionMemory:
    def __init__(self, redis_url: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.local_history: dict[str, list[dict[str, str]]] = defaultdict(list)

    @staticmethod
    def storage_key(identity: IdentityContext, session_id: str) -> str:
        parts = (identity.tenant_id, identity.user_id, session_id)
        encoded_parts = (quote(part, safe="-._") for part in parts)
        return "smart-commerce:session:" + ":".join(encoded_parts)

    async def append(self, identity: IdentityContext, session_id: str, role: str, content: str) -> None:
        item = {"role": role, "content": content}
        storage_key = self.storage_key(identity, session_id)
        try:
            await self.redis.rpush(storage_key, json.dumps(item, ensure_ascii=False))
            await self.redis.expire(storage_key, 60 * 60 * 24)
        except Exception:
            logger.warning("redis_append_failed session_id=%s role=%s", session_id, role, exc_info=True)
            self.local_history[storage_key].append(item)

    async def status(self) -> str:
        try:
            await self.redis.ping()
            return "ok"
        except Exception:
            logger.warning("redis_status_failed", exc_info=True)
            return "fallback"
