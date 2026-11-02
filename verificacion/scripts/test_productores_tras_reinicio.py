"""Tras reiniciar RabbitMQ: Usuarios publica user.preferences.updated e Ingesta publica article.ingested."""
import asyncio
from lib import ADMIN, Tap, check, http, login, registrar, set_prefs, wait_until

async def main():
    st = http().get("/api/status").json()
    check("/api/status ok en los 5 servicios", st["status"] == "ok", str({k: v["status"] for k, v in st["services"].items()}))
    async with Tap(["user.preferences.updated", "article.ingested"]) as t:
        _, tok, u = registrar(); set_prefs(tok, u["user_id"], categories=["salud"])
        check("Usuarios publica tras el reinicio", await wait_until(lambda: t.of("user.preferences.updated", user_id=u["user_id"]), 10))
        a = http(login(**ADMIN))
        r = a.post("/api/sources", json={"name": "El País Ciencia", "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/ciencia/portada"})
        sid = r.json().get("id"); a.post(f"/api/sources/{sid}/scrape")
        ok = await wait_until(lambda: any(e["payload"].get("source_id") == sid for e in t.of("article.ingested")), 40)
        check("Ingesta publica tras el reinicio (fuente nueva)", ok, f"{sum(e['payload'].get('source_id') == sid for e in t.of('article.ingested'))} eventos")

asyncio.run(main())
