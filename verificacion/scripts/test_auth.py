"""Registro, login, roles, permisos del gateway y fuentes por usuario (arquitectura 7.1, eventos 3.5)."""
import asyncio, uuid, jwt, websockets
from lib import (ADMIN, Tap, WsClient, check, classified_example, envelope, http, ingested_example, login,
                 publish, registrar, set_prefs, wait_until)


async def main():
    pub = http()
    # --- Registro ---
    d, tok, u = registrar()
    check("registro 201 + login: rol usuario, sin contraseña en la respuesta",
          u["role"] == "usuario" and "password" not in str(u) and u["username"] == d["username"]
          and u["first_names"] == "Ana María" and u["last_names"] == "Pérez Loja", str({k: u[k] for k in ("username", "role")}))
    for nombre, cambio, esperado in [
        ("correo repetido (mayúsculas) -> 409", {"email": d["email"].upper(), "username": f"x.{uuid.uuid4().hex[:6]}"}, 409),
        ("username repetido -> 409", {"username": d["username"]}, 409),
        ("contraseña corta -> 422", {"password": "corta"}, 422),
        ("username inválido -> 422", {"username": "Con Espacios"}, 422),
        ("correo inválido -> 422", {"email": "no-es-correo"}, 422),
        ("apellidos vacíos -> 422", {"last_names": "  "}, 422)]:
        body = {"email": f"n-{uuid.uuid4().hex[:6]}@ejemplo.com", "password": "clave-segura-1", "first_names": "A",
                "last_names": "B", "username": f"n.{uuid.uuid4().hex[:6]}"}
        body.update(cambio)
        r = pub.post("/api/users", json=body)
        check(f"registro: {nombre}", r.status_code == esperado, f"{r.status_code} {r.json().get('detail')}")
    r = pub.post("/api/users", json={"email": "x@y.co", "password": "clave-segura-1"})
    check("registro sin nombres/username -> 422", r.status_code == 422)
    # --- Login ---
    check("login contraseña incorrecta -> 401", pub.post("/api/auth/login", json={"email": d["email"], "password": "otra-clave"}).status_code == 401)
    check("login correo inexistente -> 401", pub.post("/api/auth/login", json={"email": "nadie@ejemplo.com", "password": "x" * 8}).status_code == 401)
    claims = jwt.decode(tok, options={"verify_signature": False})
    check("JWT: sub=user_id, role, exp a 8 h", claims["sub"] == u["user_id"] and claims["role"] == "usuario"
          and 7.9 * 3600 < claims["exp"] - claims["iat"] <= 8 * 3600)
    # --- Sin token / token falso / cabeceras falsificadas ---
    check("GET /api/users/me sin token -> 401", pub.get("/api/users/me").status_code == 401)
    check("GET /api/search sin token -> 401", pub.get("/api/search").status_code == 401)
    check("GET /api/categories sin token -> 200 (pública)", pub.get("/api/categories").status_code == 200)
    falso = jwt.encode({"sub": u["user_id"], "role": "admin", "exp": claims["exp"]}, "otro-secreto", algorithm="HS256")
    check("token firmado con otro secreto -> 401", http(falso).get("/api/users/me").status_code == 401)
    r = pub.get("/api/users/me", headers={"X-User-Id": u["user_id"], "X-User-Role": "admin"})
    check("X-User-Id/X-User-Role enviados por el cliente sin token -> 401", r.status_code == 401)
    c = http(tok)
    me = c.get("/api/users/me")
    check("GET /api/users/me con token -> 200", me.status_code == 200 and me.json()["user_id"] == u["user_id"])
    check("GET /api/users?email= (entrar sin contraseña) ya no existe",
          c.get("/api/users", params={"email": d["email"]}).status_code in (404, 405))
    # --- Otro usuario y admin ---
    d2, tok2, u2 = registrar()
    check("usuario lee a otro -> 403", c.get(f"/api/users/{u2['user_id']}").status_code == 403)
    check("usuario cambia preferencias de otro -> 403",
          c.put(f"/api/users/{u2['user_id']}/preferences", json={"categories": [], "keywords": []}).status_code == 403)
    r = c.get(f"/api/users/{u['user_id']}", headers={"X-User-Id": u2["user_id"]})
    check("cabecera X-User-Id falsificada con token propio -> la ignora el gateway", r.status_code == 200 and r.json()["user_id"] == u["user_id"])
    atok = login(**ADMIN); a = http(atok)
    check("admin inicial: login y rol admin", a.get("/api/users/me").json()["role"] == "admin")
    check("admin lee a otro usuario -> 200", a.get(f"/api/users/{u2['user_id']}").status_code == 200)
    check("admin cambia preferencias de otro -> 403 (solo las propias)",
          a.put(f"/api/users/{u2['user_id']}/preferences", json={"categories": [], "keywords": []}).status_code == 403)
    # --- Fuentes ---
    fuentes = c.get("/api/sources").json()
    check("usuario: GET /api/sources -> 200", len(fuentes) >= 4, f"{len(fuentes)} fuentes")
    f0 = fuentes[0]
    r = c.post("/api/sources", json={"name": "X", "url": "https://ejemplo.com/rss.xml"})
    check("usuario: POST /api/sources -> 403", r.status_code == 403, r.json().get("detail"))
    check("usuario: POST /api/sources/{id}/scrape -> 403", c.post(f"/api/sources/{f0['id']}/scrape").status_code == 403)
    r = a.post("/api/sources", json={"name": f0["name"], "url": f0["url"]})
    check("admin: POST /api/sources pasa el gateway (409 por URL repetida)", r.status_code == 409, str(r.status_code))
    check("admin: POST /api/sources/{id}/scrape -> 202", a.post(f"/api/sources/{f0['id']}/scrape").status_code == 202)
    # --- Notificaciones: solo las propias ---
    check("GET /api/notifications de otro -> 403",
          c.get("/api/notifications", params={"user_id": u2["user_id"]}).status_code == 403)
    check("GET /api/notifications propias -> 200", c.get("/api/notifications", params={"user_id": u["user_id"]}).status_code == 200)
    # --- WebSocket ---
    async def cierre(q):
        try:
            async with websockets.connect(f"ws://localhost:8080/ws/notifications{q}", open_timeout=10) as w:
                await asyncio.wait_for(w.recv(), 5); return "abierto"
        except websockets.ConnectionClosed as e:
            return e.rcvd.code if e.rcvd else None
    check("WS sin token -> 1008", await cierre("") == 1008)
    check("WS con user_id (forma antigua) -> 1008", await cierre(f"?user_id={u['user_id']}") == 1008)
    check("WS con token falso -> 1008", await cierre(f"?token={falso}") == 1008)
    # --- disabled_sources y source_id ---
    fuente_off, fuente_on = "aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"
    async with Tap(["user.preferences.updated"]) as tap:
        set_prefs(tok, u["user_id"], categories=["tecnologia"], disabled_sources=[fuente_off, fuente_off, " "])
        await wait_until(lambda: tap.of("user.preferences.updated", user_id=u["user_id"]), 10)
    ev = tap.of("user.preferences.updated", user_id=u["user_id"])
    check("user.preferences.updated lleva disabled_sources (sin repetidos ni vacíos)",
          ev and ev[-1]["payload"].get("disabled_sources") == [fuente_off], str(ev[-1]["payload"] if ev else None))
    await asyncio.sleep(1.5)
    async with WsClient(tok) as ws, Tap(["article.classified"]) as tc:
        apagada = classified_example(source_id=fuente_off)
        encendida = classified_example(source_id=fuente_on)
        sin_id = classified_example(); sin_id.pop("source_id")
        for p in (apagada, encendida, sin_id):
            await publish(envelope("article.classified", p))
        await wait_until(lambda: ws.for_article(encendida["article_id"]) and ws.for_article(sin_id["article_id"]), 10)
        await asyncio.sleep(1.5)
        check("alerta de fuente encendida -> llega", len(ws.for_article(encendida["article_id"])) == 1)
        check("alerta sin source_id -> llega (no se filtra)", len(ws.for_article(sin_id["article_id"])) == 1)
        check("alerta de fuente apagada -> NO llega", not ws.for_article(apagada["article_id"]))
        # source_id de punta a punta
        ing = ingested_example(title="Nuevo chip de inteligencia artificial para computadoras", source_id=fuente_on,
                               body="El procesador acelera el aprendizaje automático en servidores y portátiles.")
        await publish(envelope("article.ingested", ing))
        await wait_until(lambda: tc.of("article.classified", article_id=ing["article_id"]), 15)
        cl = tc.of("article.classified", article_id=ing["article_id"])
        check("Clasificación copia source_id a article.classified", cl and cl[0]["payload"].get("source_id") == fuente_on)
    await asyncio.sleep(1.5)
    art = c.get(f"/api/articles/{ing['article_id']}").json()
    item = [i for i in c.get("/api/search", params={"q": "chip inteligencia artificial computadoras"}).json()["items"]
            if i["article_id"] == ing["article_id"]]
    check("Búsqueda guarda y devuelve source_id (detalle y lista)", art.get("source_id") == fuente_on
          and item and item[0].get("source_id") == fuente_on)
    # --- PATCH de una alerta ajena ---
    alerta = c.get("/api/notifications", params={"user_id": u["user_id"]}).json()[0]
    check("PATCH /read de una alerta ajena -> 404", http(tok2).patch(f"/api/notifications/{alerta['notification_id']}/read").status_code == 404)
    check("PATCH /read de la propia -> 200", c.patch(f"/api/notifications/{alerta['notification_id']}/read").status_code == 200)


asyncio.run(main())
