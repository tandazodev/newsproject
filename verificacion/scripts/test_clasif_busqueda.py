"""Clasificación y Búsqueda con article.ingested de docs/eventos.md (vía RabbitMQ y gateway con token)."""
import asyncio, json, uuid
from lib import ADMIN, Tap, check, envelope, http, ingested_example, login, publish, queues, registrar, wait_until

CATS = {"politica", "economia", "tecnologia", "deportes", "salud", "cultura", "internacional", "otros"}
REQ = {"article_id", "url", "title", "summary", "source", "published_at", "ingested_at", "category", "tags", "score"}


async def main():
    _, tok, _ = registrar(); c = http(tok)
    check("GET /api/categories (pública)", set(http().get("/api/categories").json()["categories"]) == CATS)
    j = c.get("/api/model").json()
    check("GET /api/model con métricas", j.get("f1_macro") is not None, json.dumps({k: j.get(k) for k in ("version", "algorithm", "f1_macro")}))
    r = c.post("/api/classify", json={"title": "Apple presenta un nuevo iPhone con inteligencia artificial", "body": "Incluye un chip más rápido."})
    check("POST /api/classify", r.status_code == 200 and r.json()["category"] in CATS, r.text[:100])
    check("POST /api/classify vacío -> 422", c.post("/api/classify", json={"title": " ", "body": "x"}).status_code == 422)
    q0 = queues()
    async with Tap(["article.classified"]) as tap:
        p = ingested_example(title="Vacunación masiva contra la gripe en Loja",
                             body="El Ministerio de Salud inició la campaña de vacunación en hospitales para prevenir la influenza.")
        ev = envelope("article.ingested", p); await publish(ev)
        await wait_until(lambda: tap.of("article.classified", article_id=p["article_id"]), 15)
        out = tap.of("article.classified", article_id=p["article_id"])
        check("ingested válido -> exactamente 1 classified", len(out) == 1)
        if out:
            pl = out[0]["payload"]
            check("classified: obligatorios, ingested_at, image_url y source_id copiados", REQ <= pl.keys()
                  and pl["ingested_at"] == ev["occurred_at"] and pl["image_url"] == p["image_url"] and pl["source_id"] == p["source_id"],
                  f"{pl['category']} {pl['score']}")
        await publish(envelope("article.ingested", p)); await asyncio.sleep(3)
        check("ingested repetido -> sin nuevo classified", len(tap.of("article.classified", article_id=p["article_id"])) == 1)
        p2 = ingested_example(image_url=None, campo_nuevo="x", title="La selección gana el partido", body="Venció 2 a 0 en el estadio.")
        p2.pop("source_id")
        await publish(envelope("article.ingested", p2))
        await wait_until(lambda: tap.of("article.classified", article_id=p2["article_id"]), 15)
        o2 = tap.of("article.classified", article_id=p2["article_id"])
        check("image_url null, sin source_id y campo desconocido -> se clasifica", len(o2) == 1 and o2[0]["payload"]["image_url"] is None)
        p3 = ingested_example(); p3.pop("title")
        await publish(envelope("article.ingested", p3)); await publish(b"{roto", routing_key="article.ingested")
        dlq = "clasificacion.article-ingested.dlq"
        ok = await wait_until(lambda: queues()[dlq][0] >= q0[dlq][0] + 2, 20, 2)
        check("sin title y JSON roto -> .dlq (+2)", ok, f"{q0[dlq][0]} -> {queues()[dlq][0]}")
    await asyncio.sleep(2); aid = p["article_id"]
    check("GET /api/articles/{id} indexado", c.get(f"/api/articles/{aid}").json().get("article_id") == aid)
    check("GET /api/articles/{id} inexistente -> 404", c.get(f"/api/articles/{uuid.uuid4()}").status_code == 404)
    for q in ("vacunación", "vacunacion", "VACUNACION"):
        check(f"search q={q}", aid in [i["article_id"] for i in c.get("/api/search", params={"q": q}).json()["items"]])
    cat = c.get(f"/api/articles/{aid}").json()["category"]; otra = "deportes" if cat != "deportes" else "salud"
    check(f"search q + category={cat} lo incluye y {otra} no",
          aid in [i["article_id"] for i in c.get("/api/search", params={"q": "vacunacion", "category": cat}).json()["items"]]
          and aid not in [i["article_id"] for i in c.get("/api/search", params={"q": "vacunacion", "category": otra}).json()["items"]])
    check("search category inválida -> 422", c.get("/api/search", params={"category": "inventada"}).status_code == 422)
    q1 = queues()["busqueda.article-classified.dlq"][0]
    await publish(envelope("article.classified", {"article_id": "no-uuid"}))
    check("busqueda: classified inválido -> .dlq", await wait_until(lambda: queues()["busqueda.article-classified.dlq"][0] > q1, 20, 2))


asyncio.run(main())
