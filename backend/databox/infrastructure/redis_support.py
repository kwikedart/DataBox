"""Redis epoch cache, document lock, and collaboration fan-out."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID


class RedisEpochCache:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any | None = None

    async def _redis(self) -> Any:
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    async def get(self, key: str) -> int | None:
        raw = await (await self._redis()).get(key)
        if raw is None:
            return None
        return int(raw)

    async def set(self, key: str, value: int) -> bool:
        try:
            await (await self._redis()).set(key, int(value))
            return True
        except Exception:
            return False

    async def delete(self, key: str) -> None:
        try:
            await (await self._redis()).delete(key)
        except Exception:
            return None


class RedisDocumentLock:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any | None = None

    async def _redis(self) -> Any:
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    async def acquire(self, document_id: UUID) -> bool:
        try:
            return bool(await (await self._redis()).set(f"databox:lock:{document_id}", "1", nx=True, ex=15))
        except Exception:
            return False

    async def release(self, document_id: UUID) -> None:
        try:
            await (await self._redis()).delete(f"databox:lock:{document_id}")
        except Exception:
            return None


_CONSUME_TICKET = """
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
"""


class RedisTicketStore:
    """Single-use collaboration tickets shared across API instances."""

    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url)

    def put(self, token_hash: str, expires_at, payload: dict) -> None:
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        ttl = max(1, int((expires_at - now).total_seconds()))
        self._redis.set(f"databox:ticket:{token_hash}", json.dumps(payload), ex=ttl)

    def consume(self, token_hash: str, now) -> dict | None:
        import json

        raw = self._redis.eval(_CONSUME_TICKET, 1, f"databox:ticket:{token_hash}")
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        del now
        return payload


class RedisFanout:
    """Cross-instance collaboration broadcast. Payloads are Yjs frames, never document text."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._tasks: dict[int, asyncio.Task] = {}

    async def publish(self, document_id: UUID, message: bytes) -> None:
        import redis.asyncio as redis

        client = redis.from_url(self._url)
        try:
            await client.publish(f"databox:collab:{document_id}", message)
        finally:
            await client.aclose()

    def subscribe(self, document_id: UUID) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(self._listen(document_id, queue))
        self._tasks[id(queue)] = task
        return queue

    def unsubscribe(self, document_id: UUID, queue: asyncio.Queue) -> None:
        del document_id
        task = self._tasks.pop(id(queue), None)
        if task is not None:
            task.cancel()

    async def _listen(self, document_id: UUID, queue: asyncio.Queue) -> None:
        import redis.asyncio as redis

        client = redis.from_url(self._url)
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(f"databox:collab:{document_id}")
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, str):
                    data = data.encode("utf-8")
                if isinstance(data, bytes):
                    await queue.put(data)
        except asyncio.CancelledError:
            raise
        finally:
            await pubsub.aclose()
            await client.aclose()
