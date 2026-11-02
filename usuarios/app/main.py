"""Usuarios — microservicio (responsable: Ariana).

Registro con contraseña, inicio de sesión (JWT), roles y preferencias.
Publica user.preferences.updated y expone (docs/arquitectura.md, secciones 7 y 7.1):
  POST /api/users                    registro público (rol "usuario")
  POST /api/auth/login               correo + contraseña -> JWT
  GET  /api/users/me                 usuario del token (X-User-Id, lo pone el gateway)
  GET  /api/users/{id}
  PUT  /api/users/{id}/preferences   categorías, keywords, notificaciones y fuentes desactivadas

El gateway valida el JWT y aplica los permisos; este servicio además rechaza (403)
que un usuario no administrador lea o cambie a otro (defensa en profundidad).
"""
import asyncio
import json
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import aio_pika
import asyncpg
import bcrypt
import jwt
from asyncpg.exceptions import UniqueViolationError
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

SERVICE = "usuarios"
DATABASE_URL = os.environ["DATABASE_URL"]
RABBITMQ_URL = os.environ["RABBITMQ_URL"]
JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip().lower()
JWT_HORAS = 8
EXCHANGE = "newsproject.events"
ROUTING_KEY_PREF = "user.preferences.updated"
CATEGORIAS_VALIDAS = [
    "politica", "economia", "tecnologia", "deportes",
    "salud", "cultura", "internacional", "otros",
]
ROLES = ("admin", "usuario")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,30}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 72  # bcrypt solo usa los primeros 72 bytes

# CREATE ... IF NOT EXISTS + ALTER ... ADD COLUMN IF NOT EXISTS: arranca igual con una BD
# nueva o con una de la versión anterior (los usuarios sin contraseña no pueden entrar).
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_names TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_names TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'usuario';
CREATE UNIQUE INDEX IF NOT EXISTS users_username_uk ON users (username);
CREATE TABLE IF NOT EXISTS preferences (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    categories TEXT[] NOT NULL DEFAULT '{}',
    keywords TEXT[] NOT NULL DEFAULT '{}',
    notifications_enabled BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ
);
ALTER TABLE preferences ADD COLUMN IF NOT EXISTS disabled_sources TEXT[] NOT NULL DEFAULT '{}';
"""

USER_SELECT = """
    SELECT u.user_id, u.email, u.username, u.first_names, u.last_names, u.name, u.role,
           u.created_at, p.categories, p.keywords, p.notifications_enabled,
           p.disabled_sources, p.updated_at
    FROM users u
    LEFT JOIN preferences p ON p.user_id = u.user_id
"""

# Estado compartido del proceso; lo llena el arranque en segundo plano.
state = {"pool": None, "amqp": None, "channel": None, "exchange": None}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(stage, **fields):
    """Una línea JSON por evento (regla 10 de docs/eventos.md)."""
    print(json.dumps({"ts": utc_now(), "service": SERVICE, "stage": stage, **fields},
                     ensure_ascii=False), flush=True)


async def with_retries(name, connect):
    """Reintenta `connect` con espera creciente (1, 2, 4… hasta 30 s)."""
    delay = 1
    attempt = 1
    while True:
        try:
            return await connect()
        except Exception as exc:  # noqa: BLE001 — cualquier fallo de conexión se reintenta
            log(f"{name}.retry", attempt=attempt, wait_s=delay, error=str(exc))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
            attempt += 1


def iso_z(value, timespec="seconds"):
    """Formatea un datetime aware a ISO 8601 UTC con sufijo Z."""
    return value.astimezone(timezone.utc).isoformat(timespec=timespec).replace("+00:00", "Z")


def error(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def no_disponible():
    if state["pool"] is None or state["exchange"] is None:
        return error(503, "servicio no disponible")
    return None


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def password_ok(password, password_hash):
    if not password_hash:
        return False  # usuario de la versión anterior, sin contraseña
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def crear_token(user_id, role):
    ahora = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "role": role, "iat": ahora, "exp": ahora + timedelta(hours=JWT_HORAS)}
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def a_formato(row):
    """Respuesta pública de un usuario (nunca incluye la contraseña ni su hash)."""
    if row is None:
        return None
    return {
        "user_id": str(row["user_id"]),
        "email": row["email"],
        "username": row["username"],
        "first_names": row["first_names"],
        "last_names": row["last_names"],
        "name": row["name"],
        "role": row["role"],
        "created_at": iso_z(row["created_at"]),
        "preferences": {
            "categories": list(row["categories"] or []),
            "keywords": list(row["keywords"] or []),
            "notifications_enabled": row["notifications_enabled"],
            "disabled_sources": list(row["disabled_sources"] or []),
            "updated_at": iso_z(row["updated_at"]) if row["updated_at"] else None,
        },
    }


async def usuario_por_id(user_id):
    return a_formato(await state["pool"].fetchrow(USER_SELECT + " WHERE u.user_id = $1", user_id))


def acceso_denegado(user_id, x_user_id, x_user_role):
    """403 si quien llama (cabeceras del gateway) no es el usuario ni un administrador."""
    if x_user_id is None or x_user_role == "admin":
        return None
    return None if x_user_id == str(user_id) else error(403, "no puedes acceder a otro usuario")


async def publicar_preferencias_actualizadas(user_id, categories, keywords, notifications_enabled,
                                             disabled_sources, occurred_at):
    """Publica user.preferences.updated en newsproject.events (persistente)."""
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": ROUTING_KEY_PREF,
        "occurred_at": occurred_at,
        "version": 1,
        "payload": {
            "user_id": str(user_id),
            "categories": categories,
            "keywords": keywords,
            "notifications_enabled": notifications_enabled,
            "disabled_sources": disabled_sources,
        },
    }
    await state["exchange"].publish(
        aio_pika.Message(
            json.dumps(event, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=event["event_id"],
        ),
        routing_key=ROUTING_KEY_PREF,
    )
    log("preferences.published", event_id=event["event_id"], user_id=str(user_id))


class UserCreate(BaseModel):
    email: str
    password: str
    first_names: str
    last_names: str
    username: str


class LoginRequest(BaseModel):
    email: str
    password: str


class PreferencesUpdate(BaseModel):
    categories: list[str]
    keywords: list[str]
    notifications_enabled: bool = True
    disabled_sources: list[str] = []


async def insertar_usuario(conn, *, email, username, first_names, last_names, password, role):
    user_id = uuid.uuid4()
    async with conn.transaction():
        await conn.execute(
            """INSERT INTO users (user_id, email, name, username, first_names, last_names,
                                  password_hash, role)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            user_id, email, f"{first_names} {last_names}".strip(), username, first_names,
            last_names, hash_password(password), role,
        )
        await conn.execute("INSERT INTO preferences (user_id) VALUES ($1)", user_id)
    return user_id


async def crear_admin_inicial(pool):
    """Crea el primer administrador desde el .env si ese correo aún no existe."""
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        log("admin.not_configured")
        return
    async with pool.acquire() as conn:
        if await conn.fetchval("SELECT 1 FROM users WHERE email = $1", ADMIN_EMAIL):
            return
        try:
            await insertar_usuario(conn, email=ADMIN_EMAIL, username=ADMIN_USERNAME,
                                   first_names="Administrador", last_names="", password=ADMIN_PASSWORD,
                                   role="admin")
            log("admin.created", email=ADMIN_EMAIL)
        except UniqueViolationError:
            log("admin.username_taken", username=ADMIN_USERNAME)


async def startup():
    pool = await with_retries("db", lambda: asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5))
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    await crear_admin_inicial(pool)
    state["pool"] = pool
    log("db.ready")

    # Conexión y exchange se reintentan juntos: en el modo distribuido el servicio puede arrancar
    # antes de que rabbitmq-init cree el exchange, y get_exchange (verificación pasiva) fallaría.
    connection, channel, exchange = await with_retries("rabbitmq", connect_rabbitmq)
    state["channel"] = channel
    state["exchange"] = exchange
    state["amqp"] = connection

    connection.close_callbacks.add(lambda *_: log("rabbitmq.connection_lost"))
    connection.reconnect_callbacks.add(lambda *_: log("rabbitmq.reconnected"))
    log("rabbitmq.ready")


async def connect_rabbitmq():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    try:
        channel = await connection.channel()
        # El exchange ya lo crea rabbitmq-init; aquí solo se obtiene.
        exchange = await channel.get_exchange(EXCHANGE)
    except Exception:
        await connection.close()   # si no, la conexión robusta seguiría reconectando sola
        raise
    return connection, channel, exchange


@asynccontextmanager
async def lifespan(_app):
    # El arranque va en segundo plano para que /health responda mientras tanto.
    task = asyncio.create_task(startup())
    yield
    task.cancel()
    if state["amqp"] is not None:
        await state["amqp"].close()
    if state["pool"] is not None:
        await state["pool"].close()


app = FastAPI(title=SERVICE, lifespan=lifespan)

# Modo distribuido (docker-compose.distribuido.yml): el puerto del servicio queda publicado en la
# red, así que con INTERNAL_TOKEN definido solo se aceptan peticiones que traigan el mismo valor en
# X-Internal-Token (lo pone el gateway). Vacío (modo de una PC) = sin cambios. /health queda libre
# para diagnosticar la red.
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


@app.middleware("http")
async def internal_token(request: Request, call_next):
    if INTERNAL_TOKEN and request.url.path != "/health":
        sent = request.headers.get("x-internal-token", "")
        if not secrets.compare_digest(sent.encode(), INTERNAL_TOKEN.encode()):
            return JSONResponse({"detail": "token interno inválido"}, status_code=403)
    return await call_next(request)


@app.get("/health")
async def health():
    """Formato común de /health (docs/arquitectura.md, sección 7): 200 solo si BD y RabbitMQ están bien."""
    db_ok, latencia, details = False, None, {}
    try:
        t0 = time.monotonic()
        async with state["pool"].acquire(timeout=2) as conn:
            await conn.fetchval("SELECT 1")
            latencia, db_ok = round((time.monotonic() - t0) * 1000), True
            details["users"] = await conn.fetchval("SELECT count(*) FROM users")
            details["admins"] = await conn.fetchval("SELECT count(*) FROM users WHERE role = 'admin'")
    except Exception:  # noqa: BLE001
        pass
    mq_ok = (
        state["amqp"] is not None
        and not state["amqp"].is_closed
        and state["amqp"].connected.is_set()
        and not state["amqp"].reconnecting
    )
    body = {
        "status": "ok" if db_ok and mq_ok else "unavailable",
        "service": SERVICE,
        "checks": {
            "db": {"status": "ok" if db_ok else "error", "engine": "postgresql", "latency_ms": latencia},
            "rabbitmq": {"status": "ok" if mq_ok else "error"},
        },
        "details": details,
    }
    return JSONResponse(body, status_code=200 if db_ok and mq_ok else 503)


@app.post("/api/users", status_code=201)
async def registrar(body: UserCreate):
    """Registro público: siempre crea un usuario con rol "usuario"."""
    if (resp := no_disponible()) is not None:
        return resp
    email = body.email.strip().lower()
    username = body.username.strip().lower()
    first_names = " ".join(body.first_names.split())
    last_names = " ".join(body.last_names.split())
    if not EMAIL_RE.match(email):
        return error(422, "correo inválido")
    if not MIN_PASSWORD <= len(body.password.encode("utf-8")) <= MAX_PASSWORD:
        return error(422, f"la contraseña debe tener entre {MIN_PASSWORD} y {MAX_PASSWORD} caracteres")
    if not first_names or not last_names or len(first_names) > 100 or len(last_names) > 100:
        return error(422, "nombres y apellidos son obligatorios (máximo 100 caracteres cada uno)")
    if not USERNAME_RE.match(username):
        return error(422, "el username debe tener de 3 a 30 caracteres: letras minúsculas, números, '.', '_' o '-'")

    try:
        async with state["pool"].acquire() as conn:
            user_id = await insertar_usuario(conn, email=email, username=username, first_names=first_names,
                                             last_names=last_names, password=body.password, role="usuario")
    except UniqueViolationError as exc:
        if "username" in (exc.constraint_name or ""):
            return error(409, "el username ya está en uso")
        return error(409, "el correo ya está registrado")
    log("user.registered", user_id=str(user_id))
    return await usuario_por_id(user_id)


@app.post("/api/auth/login")
async def login(body: LoginRequest):
    if (resp := no_disponible()) is not None:
        return resp
    row = await state["pool"].fetchrow(USER_SELECT + " WHERE u.email = $1", body.email.strip().lower())
    password_hash = None
    if row is not None:
        password_hash = await state["pool"].fetchval(
            "SELECT password_hash FROM users WHERE user_id = $1", row["user_id"])
    if row is None or not password_ok(body.password, password_hash):
        return error(401, "correo o contraseña incorrectos")
    log("user.login", user_id=str(row["user_id"]), role=row["role"])
    return {
        "access_token": crear_token(row["user_id"], row["role"]),
        "token_type": "bearer",
        "expires_in": JWT_HORAS * 3600,
        "user": a_formato(row),
    }


@app.get("/api/users/me")
async def mi_usuario(x_user_id: str | None = Header(None)):
    if (resp := no_disponible()) is not None:
        return resp
    try:
        user_id = uuid.UUID(x_user_id or "")
    except ValueError:
        return error(401, "falta el token")
    usuario = await usuario_por_id(user_id)
    return usuario if usuario is not None else error(404, "usuario no encontrado")


@app.get("/api/users/{user_id}")
async def obtener_usuario(user_id: uuid.UUID, x_user_id: str | None = Header(None),
                          x_user_role: str | None = Header(None)):
    if (resp := no_disponible() or acceso_denegado(user_id, x_user_id, x_user_role)) is not None:
        return resp
    usuario = await usuario_por_id(user_id)
    return usuario if usuario is not None else error(404, "usuario no encontrado")


@app.put("/api/users/{user_id}/preferences")
async def actualizar_preferencias(user_id: uuid.UUID, body: PreferencesUpdate,
                                  x_user_id: str | None = Header(None)):
    if (resp := no_disponible()) is not None:
        return resp
    # Las preferencias solo las cambia su dueño (ni siquiera el administrador)
    if x_user_id is not None and x_user_id != str(user_id):
        return error(403, "solo puedes cambiar tus propias preferencias")
    # --- normalizar categorías ---
    cats_norm = [c.strip().lower() for c in body.categories]
    invalid_cats = [c for c in cats_norm if c not in CATEGORIAS_VALIDAS]
    if invalid_cats:
        return error(422, f"categorías inválidas: {', '.join(invalid_cats)}. Válidas: {', '.join(CATEGORIAS_VALIDAS)}")
    categories = list(dict.fromkeys(cats_norm))  # sin repetidas, conservando el orden

    # --- validar keywords ---
    keywords = []
    for k in body.keywords:
        k = k.strip().lower()
        if not k or k in keywords:
            continue
        if len(k) > 50:
            return error(422, f"la palabra clave '{k}' excede los 50 caracteres")
        keywords.append(k)
    if len(keywords) > 20:
        return error(422, f"máximo 20 palabras clave, se enviaron {len(keywords)}")

    # --- fuentes desactivadas (ids de Ingesta; aquí no se comprueba que existan) ---
    disabled_sources = list(dict.fromkeys(s.strip() for s in body.disabled_sources if s.strip()))
    if any(len(s) > 64 for s in disabled_sources) or len(disabled_sources) > 200:
        return error(422, "disabled_sources: máximo 200 ids de hasta 64 caracteres")

    if not await state["pool"].fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id):
        return error(404, "usuario no encontrado")

    # Transacción: actualizar preferencias y publicar el evento.
    try:
        async with state["pool"].acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    UPDATE preferences
                    SET categories = $2, keywords = $3, notifications_enabled = $4,
                        disabled_sources = $5, updated_at = now()
                    WHERE user_id = $1
                    RETURNING updated_at
                """, user_id, categories, keywords, body.notifications_enabled, disabled_sources)
                # Milisegundos: dos cambios en el mismo segundo no empatan y Notificaciones
                # puede descartar el más antiguo (docs/eventos.md, sección 5, regla 1).
                occurred_at = iso_z(row["updated_at"], timespec="milliseconds")
                await publicar_preferencias_actualizadas(
                    user_id, categories, keywords, body.notifications_enabled, disabled_sources, occurred_at)
    except Exception as exc:  # noqa: BLE001 — BD o broker: se revierte y responde 503
        log("preferences.publish_failed", error=str(exc), user_id=str(user_id))
        return error(503, "no se pudo publicar el evento, intente de nuevo")

    return await usuario_por_id(user_id)
