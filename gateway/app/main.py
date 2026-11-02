"""API Gateway — microservicio (responsable: Ariana).

Punto de entrada único. Valida el JWT y aplica los permisos de
docs/arquitectura.md (sección 7.1), enruta REST por prefijo hacia los cinco
microservicios y reenvía el WebSocket de notificaciones. Sin BD ni broker
propio.
"""
import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import jwt
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

SERVICE = "gateway"

INGESTA_URL = os.environ["INGESTA_URL"]
CLASIFICACION_URL = os.environ["CLASIFICACION_URL"]
BUSQUEDA_URL = os.environ["BUSQUEDA_URL"]
USUARIOS_URL = os.environ["USUARIOS_URL"]
NOTIFICACIONES_URL = os.environ["NOTIFICACIONES_URL"]
JWT_SECRET = os.environ["JWT_SECRET"]
# Panel del administrador (GET /api/admin/status)
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://frontend:80")
RABBITMQ_API_URL = os.environ.get("RABBITMQ_API_URL", "http://rabbitmq:15672")
RABBITMQ_MONITOR = (os.environ.get("RABBITMQ_MONITOR_USER", ""), os.environ.get("RABBITMQ_MONITOR_PASS", ""))
# Modo distribuido: secreto compartido con los servicios, que rechazan (403) lo que no venga del
# gateway. Vacío (modo de una PC) = no se envía y los servicios no lo exigen.
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

# Cada microservicio con su BD (dentro de su contenedor) y las colas que consume
GROUPS = [
    {"service": "ingesta", "label": "Ingesta", "publishes": ["article.ingested"], "queues": []},
    {"service": "clasificacion", "label": "Clasificación", "publishes": ["article.classified"],
     "queues": ["clasificacion.article-ingested"]},
    {"service": "busqueda", "label": "Búsqueda", "publishes": [], "queues": ["busqueda.article-classified"]},
    {"service": "usuarios", "label": "Usuarios", "publishes": ["user.preferences.updated"], "queues": []},
    {"service": "notificaciones", "label": "Notificaciones", "publishes": [],
     "queues": ["notificaciones.article-classified", "notificaciones.user-preferences-updated"]},
]

SERVICES = {
    "ingesta": INGESTA_URL,
    "clasificacion": CLASIFICACION_URL,
    "busqueda": BUSQUEDA_URL,
    "usuarios": USUARIOS_URL,
    "notificaciones": NOTIFICACIONES_URL,
}

ROUTES = {
    "/api/sources": "ingesta",
    "/api/categories": "clasificacion",
    "/api/classify": "clasificacion",
    "/api/model": "clasificacion",
    "/api/search": "busqueda",
    "/api/articles": "busqueda",
    "/api/users": "usuarios",
    "/api/auth": "usuarios",
    "/api/notifications": "notificaciones",
}

NOTIFICACIONES_WS_URL = os.environ.get(
    "NOTIFICACIONES_WS_URL",
    NOTIFICACIONES_URL.replace("http://", "ws://") + "/ws",
)

HOP_BY_HOP = {
    "host", "content-length", "connection", "keep-alive",
    "transfer-encoding", "upgrade", "te", "trailer",
    "proxy-authorization", "proxy-authenticate",
}
RESPONSE_SKIP = HOP_BY_HOP | {"content-encoding"}
# Cabeceras de identidad y token interno: solo las pone el gateway, nunca se copian del cliente
IDENTITY = {"x-user-id", "x-user-role", "x-internal-token"}

# Rutas sin token (método, ruta exacta)
PUBLIC = {("POST", "/api/users"), ("POST", "/api/auth/login"), ("GET", "/api/categories")}
ADMIN_ONLY = re.compile(r"^/api/sources(/[^/]+/scrape)?$")  # POST: agregar fuente y scrapear
USER_PATH = re.compile(r"^/api/users/([^/]+)(/preferences)?$")

state = {"client": None}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(stage, **fields):
    """Una línea JSON por evento."""
    print(json.dumps({"ts": utc_now(), "service": SERVICE, "stage": stage, **fields},
                     ensure_ascii=False), flush=True)


def clean_headers(headers, exclude=HOP_BY_HOP):
    return {k: v for k, v in headers.items() if k.lower() not in exclude}


def internal_headers():
    """X-Internal-Token para llamar a los servicios (vacío si INTERNAL_TOKEN no está definido)."""
    return {"X-Internal-Token": INTERNAL_TOKEN} if INTERNAL_TOKEN else {}


def decode_token(token):
    """Claims del JWT, o None si falta, está mal firmado o venció."""
    if not token:
        return None
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"require": ["sub", "exp"]})
    except jwt.PyJWTError:
        return None
    return claims if claims.get("role") in ("admin", "usuario") else None


def bearer(request):
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else None


def authorize(method, path, query, claims):
    """None si puede pasar; si no, (status, detalle). Tabla de docs/arquitectura.md, 7.1."""
    if (method, path) in PUBLIC:
        return None
    if claims is None:
        return 401, "inicia sesión: falta el token o venció"
    user_id, role = claims["sub"], claims["role"]
    if method == "POST" and ADMIN_ONLY.match(path) and role != "admin":
        return 403, "solo un administrador puede agregar fuentes o scrapear"
    m = USER_PATH.match(path)
    if m and m.group(1) != "me":
        propio = m.group(1) == user_id
        if m.group(2) and not propio:          # preferencias: solo las propias
            return 403, "solo puedes cambiar tus propias preferencias"
        if not propio and role != "admin":
            return 403, "no puedes acceder a otro usuario"
    if path == "/api/notifications" and query.get("user_id") not in (None, user_id):
        return 403, "solo puedes ver tus propias notificaciones"
    return None


def match_route(path: str):
    for prefix, service in ROUTES.items():
        if path == prefix or path.startswith(prefix + "/"):
            return service
    return None


async def startup():
    timeout = httpx.Timeout(connect=3.0, read=15.0, write=15.0, pool=15.0)
    state["client"] = httpx.AsyncClient(timeout=timeout)


async def shutdown():
    if state["client"] is not None:
        await state["client"].aclose()


@asynccontextmanager
async def lifespan(_app):
    await startup()
    yield
    await shutdown()


app = FastAPI(title=SERVICE, lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE}


@app.get("/api/status")
async def api_status():
    async def check(name, url):
        try:
            start = time.monotonic()
            resp = await state["client"].get(f"{url}/health", timeout=2.0, headers=internal_headers())
            latency_ms = round((time.monotonic() - start) * 1000)
            if resp.status_code == 200:
                return name, {"status": "ok", "http_status": resp.status_code, "latency_ms": latency_ms}
            return name, {"status": "down", "http_status": resp.status_code,
                          "latency_ms": latency_ms, "error": f"HTTP {resp.status_code}"}
        except httpx.ConnectError:
            return name, {"status": "down", "http_status": None, "error": "ConnectError"}
        except httpx.TimeoutException:
            return name, {"status": "down", "http_status": None, "error": "TimeoutException"}
        except httpx.RequestError as exc:
            return name, {"status": "down", "http_status": None, "error": type(exc).__name__}

    results = {}
    overall = "ok"
    checks = [check(name, url) for name, url in SERVICES.items()]
    for name, info in await asyncio.gather(*checks):
        results[name] = info
        if info["status"] != "ok":
            overall = "degraded"

    return JSONResponse({
        "status": overall,
        "gateway": "ok",
        "checked_at": utc_now(),
        "services": results,
    })


@app.get("/api/admin/status")
async def admin_status(request: Request):
    """Panel del administrador (docs/arquitectura.md, 7.1): estado de cada microservicio agrupado
    con su BD y sus colas, más la infraestructura (gateway, RabbitMQ, frontend). Solo rol admin."""
    claims = decode_token(bearer(request))
    if claims is None:
        return JSONResponse({"detail": "inicia sesión: falta el token o venció"}, status_code=401)
    if claims["role"] != "admin":
        return JSONResponse({"detail": "solo un administrador puede ver el panel"}, status_code=403)
    client = state["client"]

    async def health(name, url):
        start = time.monotonic()
        try:
            resp = await client.get(f"{url}/health", timeout=3.0, headers=internal_headers())
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
            return name, {"reachable": True, "http_status": resp.status_code,
                          "latency_ms": round((time.monotonic() - start) * 1000), "health": body}
        except (httpx.RequestError, ValueError) as exc:
            return name, {"reachable": False, "http_status": None, "latency_ms": None, "health": None,
                          "error": type(exc).__name__}

    async def rabbitmq():
        try:
            auth = httpx.BasicAuth(*RABBITMQ_MONITOR)
            q = await client.get(f"{RABBITMQ_API_URL}/api/queues/%2F", timeout=3.0, auth=auth,
                                 params={"columns": "name,type,messages,consumers"})
            o = await client.get(f"{RABBITMQ_API_URL}/api/overview", timeout=3.0, auth=auth,
                                 params={"columns": "rabbitmq_version,cluster_name"})
            q.raise_for_status(); o.raise_for_status()
            return {"reachable": True, "queues": {x["name"]: x for x in q.json()}, **o.json()}
        except (httpx.HTTPError, ValueError) as exc:
            return {"reachable": False, "queues": {}, "error": type(exc).__name__}

    async def frontend():
        try:
            resp = await client.get(FRONTEND_URL, timeout=3.0)
            return {"reachable": resp.status_code == 200, "http_status": resp.status_code}
        except httpx.RequestError as exc:
            return {"reachable": False, "http_status": None, "error": type(exc).__name__}

    *servicios, mq, front = await asyncio.gather(
        *(health(g["service"], SERVICES[g["service"]]) for g in GROUPS), rabbitmq(), frontend())
    servicios = dict(servicios)

    grupos = []
    for g in GROUPS:
        h = servicios[g["service"]]
        body = h["health"] or {}
        checks = body.get("checks", {})
        problemas = []
        if not h["reachable"]:
            estado = "down"
            problemas.append("el contenedor no responde (backend y BD sin datos)")
        else:
            estado = "ok" if h["http_status"] == 200 else "degraded"
            for clave, nombre in (("db", "base de datos"), ("rabbitmq", "RabbitMQ")):
                if checks.get(clave, {}).get("status") != "ok":
                    problemas.append(f"{nombre}: sin conexión")
        colas = []
        for nombre in g["queues"]:
            cola = mq["queues"].get(nombre, {})
            dlq = mq["queues"].get(f"{nombre}.dlq", {})
            colas.append({"name": nombre, "type": cola.get("type"), "messages": cola.get("messages"),
                          "consumers": cola.get("consumers"),
                          "dlq": {"name": f"{nombre}.dlq", "messages": dlq.get("messages")}})
            if mq["reachable"] and cola.get("consumers") == 0:
                problemas.append(f"{nombre}: sin consumidor")
            if mq["reachable"] and (dlq.get("messages") or 0) > 0:
                problemas.append(f"{nombre}.dlq: {dlq['messages']} mensaje(s) fallido(s)")
        if estado == "ok" and problemas:
            estado = "degraded"
        grupos.append({
            "service": g["service"], "label": g["label"], "status": estado, "problems": problemas,
            "api": {"reachable": h["reachable"], "http_status": h["http_status"], "latency_ms": h["latency_ms"]},
            "db": checks.get("db") if h["reachable"] else None,
            "rabbitmq": checks.get("rabbitmq") if h["reachable"] else None,
            "details": body.get("details", {}),
            "publishes": g["publishes"], "queues": colas,
        })

    colas_rabbit = mq["queues"].values()
    infraestructura = {
        "gateway": {"status": "ok"},
        "rabbitmq": {"status": "ok" if mq["reachable"] else "down", "version": mq.get("rabbitmq_version"),
                     "queues": len(mq["queues"]),
                     "quorum_queues": sum(1 for x in colas_rabbit if x.get("type") == "quorum"),
                     "error": mq.get("error")},
        "frontend": {"status": "ok" if front["reachable"] else "down", "http_status": front.get("http_status")},
    }
    todo_ok = all(g["status"] == "ok" for g in grupos) and all(v["status"] == "ok" for v in infraestructura.values())
    log("admin.status", user_id=claims["sub"], status="ok" if todo_ok else "degraded")
    return {"status": "ok" if todo_ok else "degraded", "checked_at": utc_now(),
            "services": grupos, "infrastructure": infraestructura}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request):
    full_path = request.url.path
    service = match_route(full_path)
    if service is None:
        return JSONResponse({"detail": "ruta no encontrada"}, status_code=404)

    claims = decode_token(bearer(request))
    denied = authorize(request.method, full_path, request.query_params, claims)
    if denied is not None:
        status, detail = denied
        log("auth.denied", method=request.method, path=full_path, status=status,
            user_id=claims and claims["sub"])
        return JSONResponse({"detail": detail}, status_code=status)

    headers = clean_headers(request.headers, exclude=HOP_BY_HOP | IDENTITY | {"authorization"})
    if claims is not None:
        headers["X-User-Id"] = claims["sub"]
        headers["X-User-Role"] = claims["role"]
    headers.update(internal_headers())

    start = time.monotonic()
    try:
        resp = await state["client"].request(
            method=request.method,
            url=f"{SERVICES[service]}{full_path}",
            params=request.query_params,
            content=await request.body(),
            headers=headers,
        )
        latency_ms = round((time.monotonic() - start) * 1000)
        log("proxy", method=request.method, path=full_path, service=service,
            status=resp.status_code, latency_ms=latency_ms)

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=clean_headers(resp.headers, exclude=RESPONSE_SKIP),
            media_type=resp.headers.get("content-type"),
        )
    except httpx.RequestError as exc:
        latency_ms = round((time.monotonic() - start) * 1000)
        log("proxy.unavailable", method=request.method, path=full_path, service=service,
            error=type(exc).__name__, latency_ms=latency_ms)
        return JSONResponse(
            {"detail": f"servicio {service} no disponible", "service": service},
            status_code=503,
        )


@app.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket):
    await websocket.accept()
    # El usuario sale del token, nunca de la URL: nadie puede escuchar las alertas de otro
    claims = decode_token(websocket.query_params.get("token"))
    if claims is None:
        await websocket.close(code=1008, reason="token requerido o vencido")
        return
    user_id = claims["sub"]

    ws_url = f"{NOTIFICACIONES_WS_URL}?user_id={quote(user_id)}"
    try:
        # websockets 13.1: websockets.connect es el cliente legacy, cuyas cabeceras van en extra_headers
        upstream = await websockets.connect(ws_url, open_timeout=5, extra_headers=internal_headers())
    except (websockets.exceptions.InvalidHandshake, OSError, asyncio.TimeoutError) as exc:
        log("ws.upstream_unavailable", user_id=user_id, error=type(exc).__name__)
        await websocket.close(code=1013, reason="notificaciones no disponible")
        return

    log("ws.open", user_id=user_id)

    async def client_to_upstream():
        try:
            while True:
                await upstream.send(await websocket.receive_text())
        except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed, RuntimeError):
            pass

    async def upstream_to_client():
        try:
            async for msg in upstream:
                text = msg if isinstance(msg, str) else msg.decode("utf-8")
                await websocket.send_text(text)
        except (websockets.exceptions.ConnectionClosed, WebSocketDisconnect, RuntimeError):
            pass

    c2u = asyncio.create_task(client_to_upstream())
    u2c = asyncio.create_task(upstream_to_client())
    done, pending = await asyncio.wait({c2u, u2c}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    await upstream.close()
    if u2c in done:
        # Notificaciones cerró la conexión: se reenvía su código y motivo (p. ej. 1008
        # "user_id requerido (UUID)") para que el navegador sepa si reintentar.
        code, reason = upstream_close(upstream)
        try:
            await websocket.close(code=code, reason=reason)
        except Exception:  # noqa: BLE001 — el cliente ya pudo haberse ido
            pass
        log("ws.closed", user_id=user_id, code=code, reason=reason)
    else:
        log("ws.closed", user_id=user_id)


def upstream_close(upstream):
    """Código y motivo con que cerró Notificaciones, si se pueden reenviar al navegador.

    1005, 1006 y 1015 son códigos reservados que no se envían en un frame de cierre
    (indican cierre sin código o caída de la conexión): en ese caso, o si no hay código,
    se responde 1013 "notificaciones no disponible" para que el navegador reconecte.
    """
    code = upstream.close_code
    reason = upstream.close_reason or ""
    if code is None or not (1000 <= code <= 1014 or 3000 <= code <= 4999) or code in (1005, 1006):
        return 1013, "notificaciones no disponible"
    return code, reason
