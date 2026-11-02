"""Utilidades comunes de las pruebas de verificación (no forman parte del repo)."""
import asyncio, json, subprocess, uuid
from datetime import datetime, timezone
from pathlib import Path
import aio_pika, httpx

REPO = Path("/home/michu117/Documents/Repositories/newsproject")
GW = "http://localhost:8080"
EXCHANGE = "newsproject.events"
# Cada ejecución guarda capturas y logs en verificacion/ejecuciones/<AAAA-MM-DD_HHMM>/.
# La fija la variable NP_EJECUCION (la crea correr.sh); si no, se usa la hora actual.
import os as _os
EJECUCION = _os.environ.get("NP_EJECUCION") or datetime.now().strftime("%Y-%m-%d_%H%M")
DIR_EJECUCION = REPO / "verificacion" / "ejecuciones" / EJECUCION
CAPTURAS = DIR_EJECUCION / "capturas"
CAPTURAS.mkdir(parents=True, exist_ok=True)


def env_example():
    vals = {}
    for line in (REPO / ".env.example").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1); vals[k.strip()] = v.strip()
    return vals


E = env_example()
AMQP_URL = f"amqp://{E['RABBITMQ_USER']}:{E['RABBITMQ_PASS']}@localhost:5672/"
ADMIN = {"email": E["ADMIN_EMAIL"], "password": E["ADMIN_PASSWORD"]}


def now_z():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def envelope(event_type, payload):
    return {"event_id": str(uuid.uuid4()), "event_type": event_type, "occurred_at": now_z(), "version": 1, "payload": payload}


def ingested_example(**over):
    url = f"https://ejemplo.com/noticia-{uuid.uuid4().hex[:8]}"
    p = {"article_id": str(uuid.uuid5(uuid.NAMESPACE_URL, url)), "url": url, "title": "Título de la noticia",
         "body": "Texto limpio del artículo...", "source": "ejemplo.com", "source_id": "6ae7aeea22e26d7d67be2610",
         "published_at": "2026-10-25T13:55:00Z", "image_url": "https://ejemplo.com/fotos/noticia-1.jpg", "hash": "sha256-del-contenido"}
    p.update(over); return p


def classified_example(**over):
    url = f"https://ejemplo.com/noticia-{uuid.uuid4().hex[:8]}"
    p = {"article_id": str(uuid.uuid5(uuid.NAMESPACE_URL, url)), "url": url, "title": "Título de la noticia",
         "summary": "Resumen corto del artículo.", "source": "ejemplo.com", "source_id": "6ae7aeea22e26d7d67be2610",
         "published_at": "2026-10-25T13:55:00Z", "ingested_at": now_z(), "image_url": "https://ejemplo.com/fotos/noticia-1.jpg",
         "category": "tecnologia", "tags": ["inteligencia-artificial", "ecuador"], "score": 0.87}
    p.update(over); return p


async def publish(event_or_bytes, routing_key=None):
    conn = await aio_pika.connect_robust(AMQP_URL)
    async with conn:
        ch = await conn.channel(); ex = await ch.get_exchange(EXCHANGE)
        body = event_or_bytes if isinstance(event_or_bytes, bytes) else json.dumps(event_or_bytes).encode()
        await ex.publish(aio_pika.Message(body, content_type="application/json", delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                         routing_key=routing_key or event_or_bytes["event_type"])


class Tap:
    """Cola temporal exclusiva (solo pruebas) que escucha el exchange."""
    def __init__(self, keys=("#",)): self.keys, self.msgs = keys, []
    async def __aenter__(self):
        self.conn = await aio_pika.connect_robust(AMQP_URL)
        ch = await self.conn.channel(); ex = await ch.get_exchange(EXCHANGE)
        q = await ch.declare_queue("", exclusive=True, auto_delete=True)
        for k in self.keys: await q.bind(ex, k)
        async def on(m):
            async with m.process(): self.msgs.append((m.routing_key, json.loads(m.body), m.delivery_mode))
        self.q = q; await q.consume(on); return self
    async def __aexit__(self, *a): await self.conn.close()
    def of(self, rk, **match):
        return [b for k, b, _ in self.msgs if k == rk and all(b.get("payload", {}).get(f) == v for f, v in match.items())]


class WsClient:
    def __init__(self, token, base="ws://localhost:8080/ws/notifications"):
        self.url, self.msgs = f"{base}?token={token}", []
    async def __aenter__(self):
        import websockets
        self.ws = await websockets.connect(self.url, open_timeout=10)
        self.task = asyncio.create_task(self._read()); await asyncio.sleep(0.5); return self
    async def _read(self):
        try:
            async for m in self.ws:
                if m != "pong": self.msgs.append((datetime.now(timezone.utc), json.loads(m)))
        except Exception: pass
    async def __aexit__(self, *a):
        self.task.cancel(); await self.ws.close()
    def for_article(self, aid):
        return [m for _, m in self.msgs if m.get("data", {}).get("article_id") == aid]


def queues():
    out = subprocess.run(["docker", "exec", "newsproject-rabbitmq", "rabbitmqctl", "-q", "list_queues", "name", "messages", "consumers"],
                         capture_output=True, text=True).stdout
    return {p[0]: (int(p[1]), int(p[2])) for p in (l.split() for l in out.splitlines()[1:]) if len(p) == 3}


def http(token=None):
    return httpx.Client(base_url=GW, timeout=15, headers={"Authorization": f"Bearer {token}"} if token else {})


def registrar(c=None, **over):
    """Registra un usuario de prueba y devuelve (datos_enviados, token, usuario)."""
    c = c or http()
    tag = uuid.uuid4().hex[:6]
    d = {"email": f"v-{tag}@ejemplo.com", "password": "clave-segura-1", "first_names": "Ana María",
         "last_names": "Pérez Loja", "username": f"v.{tag}"}
    d.update(over)
    r = c.post("/api/users", json=d); assert r.status_code == 201, r.text
    t = c.post("/api/auth/login", json={"email": d["email"], "password": d["password"]}).json()
    return d, t["access_token"], t["user"]


def login(email, password):
    return http().post("/api/auth/login", json={"email": email, "password": password}).json()["access_token"]


def set_prefs(token, user_id, **prefs):
    body = {"categories": [], "keywords": [], "notifications_enabled": True, "disabled_sources": []}; body.update(prefs)
    r = http(token).put(f"/api/users/{user_id}/preferences", json=body); assert r.status_code == 200, r.text
    return r.json()


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""), flush=True); return ok


async def wait_until(pred, timeout=15, step=0.5):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        if pred(): return True
        await asyncio.sleep(step)
    return pred()
