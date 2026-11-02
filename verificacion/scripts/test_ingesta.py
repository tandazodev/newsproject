"""Ingesta con scraping real: el admin agrega una fuente nueva y la scrapea; se validan los
article.ingested (eventos.md 3.1), que todos se clasifican, 0 a la DLQ y que un 2.º scraping no duplica."""
import asyncio, re, uuid
from collections import Counter
from lib import ADMIN, Tap, check, http, login, queues

Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
REQ = ("article_id", "url", "title", "body", "source", "published_at", "hash")
FEED = ("El País Tecnología", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/tecnologia/portada")


def errores_evento(e):
    p, err = e.get("payload", {}), []
    if not {"event_id", "event_type", "occurred_at", "version", "payload"} <= e.keys() or e.get("version") != 1:
        err.append("sobre")
    if not Z.match(str(e.get("occurred_at", ""))): err.append("occurred_at")
    err += [f"falta {f}" for f in REQ if not isinstance(p.get(f), str) or not p[f].strip()]
    if not Z.match(str(p.get("published_at", ""))): err.append("published_at")
    if p.get("article_id") != str(uuid.uuid5(uuid.NAMESPACE_URL, p.get("url", ""))): err.append("article_id")
    if not isinstance(p.get("source_id"), str): err.append("source_id")
    if p.get("image_url") is not None and not str(p["image_url"]).startswith("https://"): err.append("image_url")
    return err


async def asentar(tap, rk, quieto=6, maximo=120):
    previo, igual = -1, 0
    for _ in range(maximo):
        n = len(tap.of(rk)); igual = igual + 1 if n == previo else 0; previo = n
        if igual >= quieto and n: return n
        await asyncio.sleep(1)
    return len(tap.of(rk))


async def main():
    a = http(login(**ADMIN))
    fuentes = a.get("/api/sources").json()
    check("fuentes semilla con último estado OK", len(fuentes) == 4 and all((f.get("last_scrape") or {}).get("status") == "ok" for f in fuentes),
          "; ".join(f"{f['name']}: {(f.get('last_scrape') or {}).get('status')} found={(f.get('last_scrape') or {}).get('found')}" for f in fuentes))
    d0 = queues()["clasificacion.article-ingested.dlq"][0]
    async with Tap(["article.ingested", "article.classified"]) as tap:
        r = a.post("/api/sources", json={"name": FEED[0], "url": FEED[1]})
        check("admin agrega fuente -> 201", r.status_code == 201, str(r.status_code)); sid = r.json()["id"]
        check("scrape -> 202", a.post(f"/api/sources/{sid}/scrape").status_code == 202)
        n = await asentar(tap, "article.ingested")
        evs = [e for e in tap.of("article.ingested") if e["payload"].get("source_id") == sid]
        malos = [(e["payload"].get("url"), errores_evento(e)) for e in evs if errores_evento(e)]
        check("article.ingested válidos (3.1) con source_id de la fuente", evs and not malos, f"{len(evs)} eventos, inválidos={malos[:2]}")
        check("persistentes", all(dm == 2 for k, _, dm in tap.msgs if k == "article.ingested"))
        await asentar(tap, "article.classified", 4, 60)
        cl = {b["payload"]["article_id"]: b["payload"] for b in tap.of("article.classified")}
        ids = {e["payload"]["article_id"] for e in evs}
        check("cada ingested produce un classified (con source_id)", ids <= cl.keys() and all(cl[i].get("source_id") == sid for i in ids),
              f"{len(ids)} -> {len(ids & cl.keys())}; categorías {dict(Counter(cl[i]['category'] for i in ids & cl.keys()))}")
        await asyncio.sleep(6)
        check("0 mensajes nuevos en la DLQ de Clasificación", queues()["clasificacion.article-ingested.dlq"][0] == d0)
        antes = len(tap.of("article.ingested"))
        a.post(f"/api/sources/{sid}/scrape"); await asyncio.sleep(12)
        check("segundo scraping: 0 eventos nuevos", len(tap.of("article.ingested")) == antes, f"{len(tap.of('article.ingested')) - antes}")
    log = a.get(f"/api/sources/{sid}/log").json()
    check("/log: 2 ejecuciones, la última con new=0", len(log) >= 2 and log[0]["new"] == 0, str([(l["new"], l["started_at"]) for l in log[:2]]))
    r = a.post("/api/sources", json={"name": "x", "url": FEED[1]})
    check("URL repetida -> 409", r.status_code == 409)


asyncio.run(main())
