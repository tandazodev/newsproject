"""Panel del administrador: GET /api/admin/status (solo admin), formato común de /health,
usuario de monitoreo sin permisos de mensajería, servicio caído en rojo y la página /admin."""
import asyncio, re, subprocess, time, uuid
import aio_pika
from playwright.sync_api import expect, sync_playwright
from lib import ADMIN, CAPTURAS, E, REPO, check, http, login, registrar

SERVICIOS = ["ingesta", "clasificacion", "busqueda", "usuarios", "notificaciones"]
dc = lambda *a: subprocess.run(["docker", "compose", "--env-file", ".env.example", *a], cwd=REPO, capture_output=True)

# --- API
check("sin token -> 401", http().get("/api/admin/status").status_code == 401)
_, tok, _ = registrar()
check("usuario normal -> 403", http(tok).get("/api/admin/status").status_code == 403)
a = http(login(**ADMIN))
r = a.get("/api/admin/status"); d = r.json()
check("admin -> 200 con 5 grupos e infraestructura", r.status_code == 200 and [s["service"] for s in d["services"]] == SERVICIOS
      and set(d["infrastructure"]) == {"gateway", "rabbitmq", "frontend"}, d["status"])
motores = {s["service"]: (s["db"] or {}).get("engine") for s in d["services"]}
check("cada servicio con su BD (formato común de /health)", motores == {"ingesta": "mongodb", "clasificacion": "postgresql",
      "busqueda": "mongodb", "usuarios": "postgresql", "notificaciones": "postgresql"}
      and all(s["db"]["status"] == "ok" and s["rabbitmq"]["status"] == "ok" for s in d["services"]), str(motores))
colas = {s["service"]: [(q["name"], q["consumers"], q["dlq"]["messages"]) for q in s["queues"]] for s in d["services"]}
check("colas por servicio con consumidores y DLQ (vía usuario de monitoreo)",
      all(c == 1 for qs in colas.values() for _, c, _ in qs) and len(colas["notificaciones"]) == 2, str(colas))
rb = d["infrastructure"]["rabbitmq"]
check("RabbitMQ: versión y 8 colas quorum", rb["status"] == "ok" and rb["quorum_queues"] == 8, f"v{rb['version']}")
det = {s["service"]: s["details"] for s in d["services"]}
check("detalles: modelo, artículos, usuarios, sesiones WS", det["clasificacion"].get("f1_macro") and "articles_indexed" in det["busqueda"]
      and det["usuarios"].get("admins") == 1 and "websocket_sessions" in det["notificaciones"])
print("   estado:", d["status"], {s["service"]: (s["status"], s["problems"]) for s in d["services"]})

# --- usuario de monitoreo: no puede publicar ni consumir
async def monitor_publica():
    try:
        conn = await aio_pika.connect(f"amqp://{E['RABBITMQ_MONITOR_USER']}:{E['RABBITMQ_MONITOR_PASS']}@localhost:5672/")
        async with conn:
            ch = await conn.channel()
            ex = await ch.get_exchange("newsproject.events")
            await ex.publish(aio_pika.Message(b"{}"), routing_key="article.ingested")
            await asyncio.sleep(0.5); return "publicó"
    except Exception as e:
        return type(e).__name__
res = asyncio.run(monitor_publica())
check("usuario de monitoreo no puede publicar en el exchange", res != "publicó", res)

# --- servicio caído
dc("stop", "busqueda")
for _ in range(20):   # las estadísticas de consumidores de RabbitMQ se actualizan con unos segundos de retraso
    d = a.get("/api/admin/status").json()
    b = next(s for s in d["services"] if s["service"] == "busqueda")
    if b["queues"][0]["consumers"] == 0:
        break
    time.sleep(2)
check("búsqueda detenida -> 'down', cola sin consumidor y estado global 'degraded'",
      b["status"] == "down" and b["queues"][0]["consumers"] == 0 and d["status"] == "degraded", str(b["problems"]))

# --- página /admin
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    pg = br.new_context(viewport={"width": 1280, "height": 900}, locale="es-EC").new_page()
    errores = []; pg.on("pageerror", lambda e: errores.append(str(e)))
    pg.goto("http://localhost:3000/login")
    pg.get_by_label("Correo").fill(ADMIN["email"]); pg.get_by_label("Contraseña").fill(ADMIN["password"])
    pg.get_by_role("button", name="Entrar").click(); expect(pg).to_have_url(re.compile("/feed$"))
    pg.locator("nav.menu").get_by_role("link", name="Panel").click()
    expect(pg.locator("article.svc")).to_have_count(8, timeout=10000)
    check("admin: enlace 'Panel' y 5 tarjetas + 3 de infraestructura", True)
    check("búsqueda caída se ve en rojo", pg.locator("article.svc-down", has_text="Búsqueda").count() == 1)
    pg.screenshot(path=str(CAPTURAS / "panel-admin-busqueda-caida.png"), full_page=True)
    dc("start", "busqueda")
    t0 = time.time()
    try:
        expect(pg.locator("article.svc", has_text="Búsqueda")).not_to_have_class(re.compile("svc-down"), timeout=60000); ok = True
    except AssertionError:
        ok = False
    check("al volver, el panel se actualiza solo (refresco cada 10 s)", ok, f"{time.time() - t0:.0f} s")
    pg.wait_for_timeout(1000)
    pg.screenshot(path=str(CAPTURAS / "panel-admin.png"), full_page=True)
    m = br.new_context(viewport={"width": 390, "height": 800}).new_page()
    m.goto("http://localhost:3000/login")
    m.get_by_label("Correo").fill(ADMIN["email"]); m.get_by_label("Contraseña").fill(ADMIN["password"])
    m.get_by_role("button", name="Entrar").click(); expect(m).to_have_url(re.compile("/feed$"))
    m.goto("http://localhost:3000/admin")
    expect(m.locator("article.svc").first).to_be_visible(timeout=10000)
    check("móvil: panel sin scroll horizontal", m.evaluate("document.documentElement.scrollWidth") <= 390)
    m.screenshot(path=str(CAPTURAS / "panel-admin-movil.png"), full_page=True)
    # usuario normal
    u = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
    u.goto("http://localhost:3000/login")
    tag = uuid.uuid4().hex[:5]
    d2, tok2, _ = registrar()
    u.get_by_label("Correo").fill(d2["email"]); u.get_by_label("Contraseña").fill(d2["password"])
    u.get_by_role("button", name="Entrar").click(); expect(u).to_have_url(re.compile("/feed$"))
    check("usuario normal: no ve 'Panel'", u.locator("nav.menu").get_by_role("link", name="Panel").count() == 0)
    u.goto("http://localhost:3000/admin"); expect(u).to_have_url(re.compile("/feed$"))
    check("usuario normal: /admin redirige al Feed", True)
    check("sin errores de JavaScript", not errores, str(errores[:2]))
    br.close()
