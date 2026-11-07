"""Autenticación del estudio.

HTTP:  `Authorization: Bearer ${STUDIO_TOKEN}` (secrets.compare_digest) en todo /api,
       salvo GET /api/health y el callback de OAuth de YouTube (lo protege el `state`
       de un solo uso: Google redirige el navegador directo a 127.0.0.1, sin el header).
WS:    /ws exige el mismo token por header `Authorization` (lo inyecta el proxy de Vite)
       o por `?token=` (clientes sin proxy, p. ej. scripts). Sin token → close 1008.
Origen: además de CORS, cualquier pedido con `Origin` fuera de la lista (front de Vite o
       el propio estudio) se corta con 403. Así una página ajena no puede usar el proxy
       de Vite (que inyecta el token) para disparar acciones por CSRF ni abrir el WS.
Sin STUDIO_TOKEN configurado todo /api responde 401 (`ylk studio` no arranca sin él).
"""
from __future__ import annotations

import json
import secrets
from urllib.parse import parse_qs

from fastapi import Header, HTTPException

from apps.studio import settings


def check_token(given: str | None) -> bool:
    expected = settings.token()
    if not expected or not given:
        return False
    return secrets.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def bearer(value: str | None) -> str | None:
    scheme, _, tok = (value or "").partition(" ")
    return tok.strip() if scheme.lower() == "bearer" and tok.strip() else None


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Dependencia de FastAPI para los routers protegidos."""
    if not check_token(bearer(authorization)):
        raise HTTPException(status_code=401, detail="Token del estudio ausente o inválido",
                            headers={"WWW-Authenticate": "Bearer"})


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}


def origin_allowed(origin: str | None, host: str | None) -> bool:
    if not origin:
        return True                      # navegación directa / curl / TestClient: sin Origin
    origin = origin.rstrip("/")
    if origin in settings.allowed_origins():
        return True
    return bool(host) and origin in (f"http://{host}", f"https://{host}")     # mismo origen


class StudioGuardMiddleware:
    """ASGI puro: Origin para HTTP y WS + token para el WebSocket de /ws."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = _headers(scope)
        if not origin_allowed(headers.get("origin"), headers.get("host")):
            if scope["type"] == "websocket":
                return await self._close_ws(receive, send)
            body = json.dumps({"detail": "Origen no permitido"}).encode()
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            return await send({"type": "http.response.body", "body": body})
        if scope["type"] == "websocket":
            query = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
            given = bearer(headers.get("authorization")) or (query.get("token") or [None])[0]
            if not check_token(given):
                return await self._close_ws(receive, send)
        return await self.app(scope, receive, send)

    @staticmethod
    async def _close_ws(receive, send):
        message = await receive()                       # websocket.connect
        if message.get("type") == "websocket.connect":
            await send({"type": "websocket.close", "code": 1008})
