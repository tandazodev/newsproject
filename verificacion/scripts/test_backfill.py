"""Relleno inicial del feed: al guardar preferencias se crean alertas con artículos recientes."""
import asyncio
from lib import WsClient, check, classified_example, envelope, http, publish, registrar, set_prefs, wait_until


def mis_alertas(tok, uid):
    return http(tok).get("/api/notifications", params={"user_id": uid}).json()


async def main():
    _, tok, u = registrar()
    async with WsClient(tok) as ws:          # Feed abierto ANTES de elegir intereses
        set_prefs(tok, u["user_id"], categories=["internacional", "deportes"])
        await wait_until(lambda: len(ws.msgs) >= 20, 15); await asyncio.sleep(1)
        al = mis_alertas(tok, u["user_id"])
        cats = {a["category"] for a in al}
        check("sin scrapear: al guardar preferencias se crean 20 alertas (máximo)", len(al) == 20, f"{len(al)} alertas, categorías {cats}")
        check("todas marcadas backfill=true y de sus categorías", all(a["backfill"] for a in al) and cats <= {"internacional", "deportes"})
        check("llegan también en vivo por WebSocket con backfill=true",
              len(ws.msgs) == 20 and all(m["data"]["backfill"] is True for _, m in ws.msgs), f"{len(ws.msgs)} mensajes")
        orden = [a["sent_at"] for a in al]
        check("sin duplicados", len({a["article_id"] for a in al}) == len(al))
        # Cambio de intereses: se agregan las nuevas coincidencias, sin repetir
        set_prefs(tok, u["user_id"], categories=["internacional", "deportes", "politica"])
        await asyncio.sleep(3)
        al2 = mis_alertas(tok, u["user_id"])
        nuevas = [a for a in al2 if a["article_id"] not in {x["article_id"] for x in al}]
        check("al agregar 'politica' se suman alertas nuevas sin duplicar", len(nuevas) > 0
              and len({a["article_id"] for a in al2}) == len(al2), f"+{len(nuevas)} ({ {a['category'] for a in nuevas} })")
        # Mismo guardado otra vez: idempotente
        set_prefs(tok, u["user_id"], categories=["internacional", "deportes", "politica"])
        await asyncio.sleep(3)
        check("guardar lo mismo otra vez no crea alertas", len(mis_alertas(tok, u["user_id"])) == len(al2))
        # Alerta en vivo posterior: no es backfill
        art = classified_example(category="deportes", title="Final del campeonato en vivo")
        await publish(envelope("article.classified", art))
        await wait_until(lambda: ws.for_article(art["article_id"]), 10)
        m = ws.for_article(art["article_id"])
        check("una noticia nueva posterior llega en vivo con backfill=false", m and m[0]["data"]["backfill"] is False)

    # Fuente apagada: el relleno la respeta
    c = http(tok)
    fuentes = {s["name"]: s["id"] for s in c.get("/api/sources").json()}
    _, tok2, u2 = registrar()
    set_prefs(tok2, u2["user_id"], categories=["internacional"], disabled_sources=[fuentes["El País"], fuentes["BBC Mundo"]])
    await asyncio.sleep(3)
    al = mis_alertas(tok2, u2["user_id"])
    fuentes_al = {a["source"] for a in al}
    check("relleno sin las fuentes apagadas (El País, BBC Mundo)", al and not fuentes_al & {"El País", "BBC Mundo"},
          f"{len(al)} alertas de {fuentes_al}")
    # Notificaciones desactivadas: sin relleno
    _, tok3, u3 = registrar()
    set_prefs(tok3, u3["user_id"], categories=["internacional"], notifications_enabled=False)
    await asyncio.sleep(3)
    check("con notificaciones desactivadas no hay relleno", len(mis_alertas(tok3, u3["user_id"])) == 0)


asyncio.run(main())
