"""Notificaciones: filtro por preferencias, WS con token, formato §7, sin duplicados, REST, DLQ."""
import asyncio, uuid, websockets
from lib import (WsClient, check, classified_example, envelope, http, publish, queues, registrar, set_prefs, wait_until)

WS_KEYS = {"notification_id", "article_id", "title", "summary", "category", "tags", "url", "image_url", "ingested_at", "sent_at"}


async def main():
    (_, ta, ua), (_, tb, ub), (_, tk, uk), (_, td, ud), (_, to, uo) = [registrar() for _ in range(5)]
    set_prefs(ta, ua["user_id"], categories=["salud"]); set_prefs(tb, ub["user_id"], categories=["cultura"])
    set_prefs(tk, uk["user_id"], keywords=["rabbitmq"]); set_prefs(td, ud["user_id"], categories=["salud"], notifications_enabled=False)
    set_prefs(to, uo["user_id"], categories=["salud"])
    await asyncio.sleep(2)
    async with WsClient(ta) as wa, WsClient(tb) as wb, WsClient(tk) as wk, WsClient(td) as wd:
        art = classified_example(category="salud", title=f"Campaña de salud {uuid.uuid4().hex[:4]}")
        await publish(envelope("article.classified", art))
        await wait_until(lambda: wa.for_article(art["article_id"]), 10); await asyncio.sleep(1)
        m = wa.for_article(art["article_id"])
        check("salud -> llega solo a quien prefiere salud", len(m) == 1 and not wb.for_article(art["article_id"])
              and not wk.for_article(art["article_id"]) and not wd.for_article(art["article_id"]))
        if m:
            d = m[0]["data"]
            check("formato WS §7 (type, campos, backfill=false, sent_at Z)", m[0]["type"] == "notification.new_article"
                  and WS_KEYS <= d.keys() and d["backfill"] is False and d["sent_at"].endswith("Z"))
        art2 = classified_example(category="economia", title="Empresas adoptan RabbitMQ", tags=[], image_url=None)
        art3 = classified_example(category="cultura", title="Festival", tags=["rabbitmq"])
        for x in (art2, art3): await publish(envelope("article.classified", x))
        await wait_until(lambda: wk.for_article(art2["article_id"]) and wk.for_article(art3["article_id"]), 10)
        check("keyword en título y en tags -> llega (image_url null)", len(wk.for_article(art2["article_id"])) == 1
              and wk.for_article(art2["article_id"])[0]["data"]["image_url"] is None and len(wk.for_article(art3["article_id"])) == 1)
        await publish(envelope("article.classified", art)); await asyncio.sleep(3)
        check("classified repetido -> sin duplicado (WS y BD)", len(wa.for_article(art["article_id"])) == 1
              and sum(a["article_id"] == art["article_id"] for a in http(ta).get("/api/notifications", params={"user_id": ua["user_id"]}).json()) == 1)
        viejo = envelope("user.preferences.updated", {"user_id": ua["user_id"], "categories": ["deportes"], "keywords": [], "notifications_enabled": True})
        viejo["occurred_at"] = "2020-01-01T00:00:00Z"; await publish(viejo); await asyncio.sleep(2)
        art4 = classified_example(category="salud"); await publish(envelope("article.classified", art4))
        await wait_until(lambda: wa.for_article(art4["article_id"]), 10)
        check("user.preferences.updated antiguo -> ignorado", len(wa.for_article(art4["article_id"])) == 1)
    r = http(to).get("/api/notifications", params={"user_id": uo["user_id"], "unread": "true"}).json()
    check("desconectado: GET ?unread=true recupera lo enviado", {art["article_id"], art4["article_id"]} <= {x["article_id"] for x in r})
    x = [a for a in r if a["article_id"] == art["article_id"]][0]
    check("PATCH /read propia -> 200 y sale de unread", http(to).patch(f"/api/notifications/{x['notification_id']}/read").status_code == 200
          and x["notification_id"] not in [y["notification_id"] for y in http(to).get("/api/notifications", params={"user_id": uo["user_id"], "unread": "true"}).json()])
    check("PATCH inexistente -> 404", http(to).patch(f"/api/notifications/{uuid.uuid4()}/read").status_code == 404)
    q0 = queues(); malo = classified_example(); malo.pop("summary")
    await publish(envelope("article.classified", malo)); await publish(b"{roto", routing_key="article.classified")
    await publish(envelope("user.preferences.updated", {"categories": []}))
    dl1, dl2 = "notificaciones.article-classified.dlq", "notificaciones.user-preferences-updated.dlq"
    ok = await wait_until(lambda: queues()[dl1][0] >= q0[dl1][0] + 2 and queues()[dl2][0] >= q0[dl2][0] + 1, 25, 2)
    check("inválidos -> sus .dlq", ok, f"{dl1}: {q0[dl1][0]}->{queues()[dl1][0]}, {dl2}: {q0[dl2][0]}->{queues()[dl2][0]}")
    q1 = queues()
    check("colas principales vacías y con consumidor", q1["notificaciones.article-classified"] == (0, 1) and q1["notificaciones.user-preferences-updated"] == (0, 1))


asyncio.run(main())
