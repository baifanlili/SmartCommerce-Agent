import json
from collections import defaultdict

from redis.asyncio import Redis
from redis.exceptions import RedisError


class SessionMemory:
    def __init__(self, redis_url: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.local_history: dict[str, list[dict[str, str]]] = defaultdict(list)

    async def append(self, session_id: str, role: str, content: str) -> None:
        item = {"role": role, "content": content}
        try:
            await self.redis.rpush(f"smart-commerce:session:{session_id}", json.dumps(item, ensure_ascii=False))
            await self.redis.expire(f"smart-commerce:session:{session_id}", 60 * 60 * 24)
        except RedisError:
            self.local_history[session_id].append(item)

    async def status(self) -> str:
        try:
            await self.redis.ping()
            return "ok"
        except RedisError:
            return "fallback"
