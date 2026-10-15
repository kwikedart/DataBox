"""Collaboration service. WebSocket connections stay off the request API."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from pycrdt import YSyncMessageType, create_sync_message, read_message

from app.deps import get_databox_application
from databox.application.service import DataboxApplication
from databox.domain.exceptions import DomainError

logger = logging.getLogger("uvicorn.error")
app = FastAPI(title="DataBox Collaboration")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


async def _forward_broadcast(websocket: WebSocket, document, payload: bytes) -> None:
    """Apply a fan-out frame to this socket's document, then deliver it. A bad frame is dropped."""
    if payload[:1] == b"\x00" and len(payload) > 2 and payload[1] in (
        YSyncMessageType.SYNC_STEP2,
        YSyncMessageType.SYNC_UPDATE,
    ):
        inner = read_message(payload[2:])
        if inner and inner != b"\x00\x00":
            try:
                document.apply_update(inner)
            except Exception:
                logger.info("collaboration_update_rejected")
                return
    await websocket.send_bytes(payload)


@app.websocket("/api/v1/collaboration/{document_id}")
async def collaboration_socket(
    websocket: WebSocket,
    document_id: UUID,
    application: DataboxApplication = Depends(get_databox_application),
):
    await websocket.accept()
    queue = None
    socket_task: asyncio.Task | None = None
    queue_task: asyncio.Task | None = None
    try:
        opening = await websocket.receive_json()
        if opening.get("type") != "auth" or not opening.get("ticket"):
            await websocket.close(code=4401)
            return
        session = await application.accept_collaboration_ticket(
            document_id=document_id,
            ticket=str(opening["ticket"]),
        )
        document = await application.load_collaboration_document(session)
        await websocket.send_json({"type": "auth_ok", "role": session.role, "canEdit": "edit" in session.actions})
        await websocket.send_bytes(create_sync_message(document))
        subscribe = getattr(application.fanout, "subscribe", None)
        if subscribe is not None:
            queue = subscribe(document_id)
        socket_task = asyncio.create_task(websocket.receive())
        queue_task = asyncio.create_task(queue.get()) if queue is not None else None
        while True:
            waiters = {socket_task}
            if queue_task is not None:
                waiters.add(queue_task)
            done, _pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if queue_task is not None and queue_task in done:
                payload = queue_task.result()
                queue_task = asyncio.create_task(queue.get())
                await _forward_broadcast(websocket, document, payload)
            if socket_task not in done:
                continue
            message = socket_task.result()
            if message.get("type") == "websocket.disconnect":
                return
            socket_task = asyncio.create_task(websocket.receive())
            if message.get("text"):
                try:
                    body = json.loads(message["text"])
                except json.JSONDecodeError:
                    await websocket.close(code=4400)
                    return
                if body.get("type") == "ping":
                    if not await application.session_still_valid(session):
                        await websocket.close(code=4401)
                        return
                    await websocket.send_json({"type": "pong"})
                continue
            frame = message.get("bytes") or b""
            effect = await application.handle_collaboration_message(session=session, frame=frame, document=document)
            if effect.reply is not None:
                await websocket.send_bytes(effect.reply)
            if effect.forward is not None:
                await application.fanout.publish(document_id, effect.forward)
    except WebSocketDisconnect:
        return
    except DomainError as exc:
        logger.info("collaboration_denied code=%s", exc.code)
        await websocket.close(code=4401)
    finally:
        if socket_task is not None:
            socket_task.cancel()
        if queue_task is not None:
            queue_task.cancel()
        unsubscribe = getattr(application.fanout, "unsubscribe", None)
        if queue is not None and unsubscribe is not None:
            unsubscribe(document_id, queue)
