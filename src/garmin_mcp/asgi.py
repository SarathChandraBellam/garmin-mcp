"""Generic ASGI entry point, usable on any ASGI host.

uvicorn garmin_mcp.asgi:app --host 0.0.0.0 --port 8000
"""

from .server import app

__all__ = ["app"]
