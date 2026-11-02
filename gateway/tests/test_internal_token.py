"""El gateway envía X-Internal-Token a los servicios (REST, /health y WebSocket) e ignora el del cliente.

Los servicios se reemplazan por un httpx.MockTransport que anota cada petición recibida.
"""
import time

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main

TOKEN = "token-de-prueba"
client = TestClient(main.app)


def jwt_usuario():
    claims = {"sub": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", "role": "usuario", "exp": int(time.time()) + 600}
    return jwt.encode(claims, main.JWT_SECRET, algorithm="HS256")


@pytest.fixture
def recibidas(monkeypatch):
    """Peticiones que llegan a los servicios simulados."""
    lista = []

    def responder(request):
        lista.append(request)
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setitem(main.state, "client", httpx.AsyncClient(transport=httpx.MockTransport(responder)))
    return lista


@pytest.fixture
def token(monkeypatch):
    return lambda valor: monkeypatch.setattr(main, "INTERNAL_TOKEN", valor)


def test_rest_envia_el_token(recibidas, token):
    token(TOKEN)
    assert client.get("/api/categories").status_code == 200
    assert recibidas[-1].headers["x-internal-token"] == TOKEN


def test_rest_ignora_el_token_que_manda_el_cliente(recibidas, token):
    token(TOKEN)
    client.get("/api/search", headers={"Authorization": f"Bearer {jwt_usuario()}", "X-Internal-Token": "falso"})
    assert recibidas[-1].headers.get_list("x-internal-token") == [TOKEN]


def test_variable_vacia_no_envia_token_ni_reenvia_el_del_cliente(recibidas, token):
    token("")
    client.get("/api/categories", headers={"X-Internal-Token": "falso"})
    assert "x-internal-token" not in recibidas[-1].headers


def test_health_de_los_servicios_lleva_el_token(recibidas, token):
    token(TOKEN)
    assert client.get("/api/status").json()["status"] == "ok"
    health = [r for r in recibidas if r.url.path == "/health"]
    assert len(health) == 5
    assert all(r.headers["x-internal-token"] == TOKEN for r in health)


@pytest.mark.parametrize("valor, esperado", [(TOKEN, {"X-Internal-Token": TOKEN}), ("", {})])
def test_websocket_envia_el_token_en_extra_headers(monkeypatch, token, valor, esperado):
    """websockets 13.1: websockets.connect es el cliente legacy y las cabeceras van en extra_headers."""
    token(valor)
    llamadas = []

    async def connect_falso(url, **kwargs):
        llamadas.append((url, kwargs))
        raise OSError("sin Notificaciones en la prueba")

    monkeypatch.setattr(main.websockets, "connect", connect_falso)
    with client.websocket_connect(f"/ws/notifications?token={jwt_usuario()}") as ws:
        with pytest.raises(WebSocketDisconnect) as cierre:
            ws.receive_text()
    assert cierre.value.code == 1013
    url, kwargs = llamadas[0]
    assert url.endswith("/ws?user_id=a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
    assert kwargs["extra_headers"] == esperado
