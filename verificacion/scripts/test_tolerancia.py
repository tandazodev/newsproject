"""Tolerancia a fallos (arquitectura §11) + Notificaciones caída y reinicio de RabbitMQ (#16).
El scraping se simula publicando article.ingested para controlar qué noticias son nuevas."""
import asyncio, subprocess, time
from lib import (ADMIN, REPO, WsClient, check, envelope, http, ingested_example, login, publish, queues,
                 registrar, set_prefs, wait_until)

def dc(*a):
    subprocess.run(["docker", "compose", "--env-file", ".env.example", *a], cwd=REPO, capture_output=True)

def tec(i):
    return ingested_example(title=f"Nuevo procesador de computadora con inteligencia artificial {i} {time.time()}",
                            body="Chip y software para computadoras portátiles con inteligencia artificial y nube.")

async def main():
    _, tok, u = registrar(); set_prefs(tok, u["user_id"], categories=["tecnologia"]); c = http(tok)
    await asyncio.sleep(2)
    idx = lambda p: c.get(f"/api/articles/{p['article_id']}").status_code == 200
    async with WsClient(tok) as ws:
        # Búsqueda caída
        dc("stop", "busqueda")
        ps = [tec(i) for i in range(3)]
        for p in ps: await publish(envelope("article.ingested", p))
        await wait_until(lambda: queues().get("busqueda.article-classified", (0, 0))[0] >= 3, 20, 2)
        q = queues()["busqueda.article-classified"]
        check("búsqueda caída: los mensajes esperan en su cola", q[0] >= 3 and q[1] == 0, f"mensajes={q[0]} consumidores={q[1]}")
        check("búsqueda caída: las alertas siguen llegando", await wait_until(lambda: all(ws.for_article(p["article_id"]) for p in ps), 10))
        check("búsqueda caída: /api/search -> 503 y el resto responde",
              c.get("/api/search").status_code == 503 and c.get("/api/sources").status_code == 200)
        dc("start", "busqueda"); t0 = time.time()
        check("búsqueda reiniciada: indexa lo pendiente", await wait_until(lambda: all(idx(p) for p in ps), 120, 2), f"{time.time() - t0:.0f} s")
        # Usuarios caído
        dc("stop", "usuarios")
        check("usuarios caído: /api/users/me -> 503", c.get("/api/users/me").status_code == 503)
        p = tec("u"); await publish(envelope("article.ingested", p))
        check("usuarios caído: la alerta llega con la copia local de preferencias", await wait_until(lambda: ws.for_article(p["article_id"]), 15))
        check("usuarios caído: Búsqueda y Notificaciones responden (token sigue válido)",
              c.get("/api/search").status_code == 200 and c.get("/api/notifications", params={"user_id": u["user_id"]}).status_code == 200)
        dc("start", "usuarios")
        # Mensaje envenenado
        d0 = queues()["clasificacion.article-ingested.dlq"][0]
        malo = ingested_example(); malo.pop("title"); bueno = tec("g")
        await publish(envelope("article.ingested", malo)); await publish(envelope("article.ingested", bueno))
        ok = await wait_until(lambda: ws.for_article(bueno["article_id"]), 15)
        okd = await wait_until(lambda: queues()["clasificacion.article-ingested.dlq"][0] == d0 + 1, 25, 2)
        check("envenenado -> .dlq y el siguiente llega por WS", ok and okd, f"dlq {d0}->{queues()['clasificacion.article-ingested.dlq'][0]}")
        # Duplicado (mismo artículo dos veces, también con hash cambiado)
        await publish(envelope("article.ingested", bueno))
        await publish(envelope("article.ingested", dict(bueno, hash="otro", body=bueno["body"] + " Actualizado.")))
        await asyncio.sleep(4)
        alertas = [a for a in c.get("/api/notifications", params={"user_id": u["user_id"]}).json() if a["article_id"] == bueno["article_id"]]
        check("duplicado: 1 alerta (WS y BD) y 1 copia en Búsqueda", len(ws.for_article(bueno["article_id"])) == 1 and len(alertas) == 1
              and idx(bueno))
    # Notificaciones caída: las alertas esperan y se recuperan
    dc("stop", "notificaciones")
    p = tec("n"); await publish(envelope("article.ingested", p))
    await wait_until(lambda: queues().get("notificaciones.article-classified", (0, 0))[0] >= 1, 20, 2)
    check("notificaciones caída: el mensaje espera en su cola", queues()["notificaciones.article-classified"][0] >= 1)
    dc("start", "notificaciones"); t0 = time.time()
    ok = await wait_until(lambda: p["article_id"] in [a["article_id"] for a in
                          (c.get("/api/notifications", params={"user_id": u["user_id"], "unread": "true"}).json()
                           if c.get("/api/notifications", params={"user_id": u["user_id"]}).status_code == 200 else [])], 180, 3)
    check("notificaciones reiniciada: procesa lo pendiente y se recupera por REST", ok, f"{time.time() - t0:.0f} s")
    # Reinicio de RabbitMQ (#16): los consumidores se recuperan solos
    dc("stop", "rabbitmq"); await asyncio.sleep(5); dc("start", "rabbitmq")
    ok = await wait_until(lambda: sum(1 for k, v in queues().items() if not k.endswith(".dlq") and v[1] == 1) == 4, 150, 5)
    check("RabbitMQ reiniciado: las 4 colas recuperan su consumidor sin reiniciar servicios", ok, str({k: v[1] for k, v in queues().items() if not k.endswith('.dlq')}))
    await wait_until(lambda: http().get("/api/categories").status_code == 200 and http(tok).get("/api/search").status_code == 200, 60, 3)
    async with WsClient(tok) as ws:
        p = tec("r"); await publish(envelope("article.ingested", p))
        check("tras el reinicio el flujo completo vuelve a funcionar", await wait_until(lambda: ws.for_article(p["article_id"]) and idx(p), 30))

asyncio.run(main())
