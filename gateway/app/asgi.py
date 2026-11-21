"""Entrada ASGI para uvicorn/gunicorn: `uvicorn gateway.app.asgi:app`."""
from gateway.app.main import create_app

app = create_app()
