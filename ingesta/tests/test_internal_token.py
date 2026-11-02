"""Token interno del modo distribuido (INTERNAL_TOKEN / X-Internal-Token).

TestClient se usa sin `with`, así que el lifespan (BD y RabbitMQ) no arranca: una ruta que
pasa el middleware responde lo que dé el servicio sin BD (por ejemplo 503), pero nunca 403.
"""
import pytest
from fastapi.testclient import TestClient

from app import main

TOKEN = "token-de-prueba"
RUTA = "/api/sources"
client = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def token(monkeypatch):
    def fijar(valor):
        monkeypatch.setattr(main.settings, "INTERNAL_TOKEN", valor)
    return fijar


def test_variable_vacia_no_exige_token(token):
    token("")
    assert client.get(RUTA).status_code != 403


def test_token_correcto_pasa(token):
    token(TOKEN)
    assert client.get(RUTA, headers={"X-Internal-Token": TOKEN}).status_code != 403


@pytest.mark.parametrize("enviado", [None, "", "otro", TOKEN + "x"])
def test_token_incorrecto_o_ausente_da_403(token, enviado):
    token(TOKEN)
    headers = {} if enviado is None else {"X-Internal-Token": enviado}
    resp = client.get(RUTA, headers=headers)
    assert resp.status_code == 403
    assert resp.json() == {"detail": "token interno inválido"}


def test_health_queda_sin_token(token):
    token(TOKEN)
    assert client.get("/health").status_code != 403
