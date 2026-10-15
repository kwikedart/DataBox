"""Separate ASGI app for the collaboration process.

Run with: uvicorn databox.collaboration_asgi:app
"""

from app.collab_main import app

__all__ = ["app"]
