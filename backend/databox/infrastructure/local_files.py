"""Private files on the local disk. Keys are server-generated, never client paths."""

from __future__ import annotations

import asyncio
from pathlib import Path

from databox.domain.exceptions import ValidationError


class LocalFileStorage:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if (
            not key
            or "\\" in key
            or key.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValidationError("Invalid object key")
        path = self._root.joinpath(*parts).resolve()
        if self._root != path and self._root not in path.parents:
            raise ValidationError("Invalid object key")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            with path.open("wb") as handle:
                view = memoryview(data)
                for offset in range(0, len(view), 64 * 1024):
                    handle.write(view[offset : offset + 64 * 1024])

        await asyncio.to_thread(_write)

    async def read_chunks(self, key: str, chunk_size: int = 64 * 1024):
        path = self._path(key)
        if not await asyncio.to_thread(path.is_file):
            raise FileNotFoundError(key)
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(handle.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def get(self, key: str) -> bytes:
        parts: list[bytes] = []
        async for chunk in self.read_chunks(key):
            parts.append(chunk)
        return b"".join(parts)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            await asyncio.to_thread(path.unlink)
