"""Demo de la sección 11 desde la app (Playwright + Chrome del sistema), con dos sesiones:
usuario normal y administrador. Escucha RabbitMQ en paralelo para ver pasar los eventos.
Capturas en verificacion/ejecuciones/<fecha_hora>/capturas/demo-*.png"""
import asyncio, re, statistics, threading, time, uuid
from playwright.sync_api import expect, sync_playwright
from lib import ADMIN, CAPTURAS, Tap, check, http, login

APP = "http://localhost:3000"


def feed_nuevo():
    """Un feed de clasificacion/data/feeds.csv aún no registrado y con ≥10 entradas (la demo agrega una
    fuente nueva para que sus noticias sean nuevas); primero los de tecnología."""
    import csv, httpx
    from lib import REPO
    registradas = {f["url"] for f in http(login(**ADMIN)).get("/api/sources").json()}
    with open(REPO / "clasificacion/data/feeds.csv", encoding="utf-8") as f:
        filas = sorted(csv.DictReader(f), key=lambda r: r["category"] != "tecnologia")
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": "newsproject-unl/1.0 (proyecto academico)"}) as c:
        for r in filas:
            if r["url"] in registradas:
                continue
            try:
                if c.get(r["url"]).text.count("<item") >= 10:
                    return f"{r['source']} {r['category']}", r["url"], r["category"]
            except httpx.HTTPError:
                pass
    raise SystemExit("No quedan feeds sin registrar en feeds.csv: haz docker compose down -v")


FEED_NUEVO = feed_nuevo()
CATEGORIA = {"politica": "Política", "economia": "Economía", "tecnologia": "Tecnología", "deportes": "Deportes",
             "salud": "Salud", "cultura": "Cultura", "internacional": "Internacional"}[FEED_NUEVO[2]]
print(f"   fuente nueva para la demo: {FEED_NUEVO[0]} {FEED_NUEVO[1]}")
cap = lambda pg, n: pg.screenshot(path=str(CAPTURAS / f"demo-{n}.png"))

# --- escucha de RabbitMQ en un hilo propio (la API síncrona de Playwright usa su propio bucle)
eventos, parar = {}, threading.Event()
def escuchar():
    async def run():
        async with Tap(["#"]) as t:
            while not parar.is_set():
                await asyncio.sleep(0.3)
            for k, _, _ in t.msgs:
                eventos[k] = eventos.get(k, 0) + 1
    asyncio.run(run())
hilo = threading.Thread(target=escuchar); hilo.start(); time.sleep(1.5)

try:
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        errores = []
        def pagina(ancho=1280):
            pg = b.new_context(viewport={"width": ancho, "height": 900}, locale="es-EC").new_page()
            pg.on("pageerror", lambda e: errores.append(str(e))); return pg

        # 1. Usuario se registra y elige tecnologia
        u = pagina(); tag = uuid.uuid4().hex[:5]; email = f"demo.{tag}@ejemplo.com"
        u.goto(APP); expect(u).to_have_url(re.compile("/login$"))
        u.get_by_role("link", name="Regístrate").click()
        u.get_by_label("Nombres").fill("Daniela"); u.get_by_label("Apellidos").fill("Cueva Ordóñez")
        u.get_by_label("Username").fill(f"daniela.{tag}"); u.get_by_label("Correo").fill(email)
        u.get_by_label("Contraseña", exact=True).fill("clave-segura-1"); u.get_by_label("Repite la contraseña").fill("clave-segura-1")
        cap(u, "1-registro")
        u.get_by_role("button", name="Crear cuenta").last.click()
        expect(u).to_have_url(re.compile(r"/preferencias\?nuevo=1$"))
        u.get_by_label(CATEGORIA).check(); cap(u, "2-preferencias")
        u.get_by_role("button", name="Guardar preferencias").click()
        expect(u).to_have_url(re.compile("/feed$")); expect(u.get_by_text("En vivo")).to_be_visible(timeout=15000)
        filas = u.locator(".filas > li")
        expect(filas.first).to_be_visible(timeout=10000)
        n0 = filas.count()
        check(f"1. registro + {CATEGORIA} -> Feed construido al instante (relleno)", n0 > 0, f"{n0} alertas 'publicada'")
        cap(u, "3-feed-usuario-nuevo")
        # usuario apaga BBC Mundo; no ve controles de admin
        u.locator("nav.menu").get_by_role("link", name="Fuentes").click()
        expect(u.locator("li.fuente").first).to_be_visible()
        check("usuario normal: sin 'Agregar fuente' ni 'Scrapear'",
              u.get_by_role("button", name="Agregar fuente").count() == 0 and u.get_by_role("button", name="Scrapear").count() == 0)
        u.locator("li.fuente", has_text="BBC Mundo").get_by_role("switch").uncheck()
        expect(u.locator("li.fuente", has_text="BBC Mundo").get_by_role("switch")).not_to_be_checked()
        cap(u, "4-fuentes-usuario")
        u.locator("nav.menu").get_by_role("link", name="Feed").click()
        expect(u.get_by_text("En vivo")).to_be_visible(timeout=15000); expect(filas.first).to_be_visible()
        check("2. user.preferences.updated pasa por RabbitMQ", True)  # se confirma con el contador al final
        antes = filas.count()

        # 3. Admin agrega una fuente nueva y la scrapea
        a = pagina(); a.goto(f"{APP}/login")
        a.get_by_label("Correo").fill(ADMIN["email"]); a.get_by_label("Contraseña").fill(ADMIN["password"])
        a.get_by_role("button", name="Entrar").click(); expect(a).to_have_url(re.compile("/feed$"))
        a.locator("nav.menu").get_by_role("link", name="Fuentes").click()
        a.get_by_label("Nombre").fill(FEED_NUEVO[0]); a.get_by_label("URL del feed RSS").fill(FEED_NUEVO[1])
        a.get_by_role("button", name="Agregar fuente").click(); expect(a.get_by_text("agregada")).to_be_visible()
        tarjeta = a.locator("li.fuente", has_text=FEED_NUEVO[0]); t0 = time.time()
        tarjeta.get_by_role("button", name="Scrapear").click()
        expect(tarjeta.get_by_text("En proceso…").first).to_be_visible(); cap(a, "5-admin-scrapear-en-proceso")
        expect(tarjeta.get_by_text(re.compile("Listo:|terminó con errores"))).to_be_visible(timeout=60000)
        res = tarjeta.locator(".aviso").inner_text()
        check("3. admin agrega y scrapea una fuente real", "Listo:" in res, res); cap(a, "6-admin-scrapear-listo")

        # 5. La alerta llega por WebSocket al Feed abierto, sin recargar
        try:
            expect(filas).not_to_have_count(antes, timeout=30000); llego = True
        except AssertionError:
            llego = False
        u.wait_for_timeout(3000)
        n = filas.count()
        check("5. las alertas aparecen en el Feed sin recargar", llego, f"{n - antes} alertas nuevas a {time.time() - t0:.1f}s de Scrapear")
        lat = [x for x in filas.locator(".fila-latencia").all_inner_texts() if re.search(r"\d", x)]
        ms = [float(x[:-3]) if x.endswith(" ms") else float(x[:-2]) * 1000 for x in lat if x.endswith((" ms", " s"))]
        check("latencia llegada − ingested_at de ≥5 alertas", len(ms) >= 5,
              f"n={len(ms)} mediana={statistics.median(ms):.0f} ms máx={max(ms):.0f} ms" if ms else "sin datos")
        badge = u.locator(".nav-link .badge").inner_text()
        cap(u, "7-feed-alertas-en-vivo")
        filas.nth(0).locator("button").click()
        titulo = u.locator(".detalle-titulo").inner_text()
        expect(u.locator(".nav-link .badge")).not_to_have_text(badge)
        check("abrir una alerta: detalle con enlace y baja el contador",
              u.get_by_role("link", name=re.compile("Leer en la fuente original")).count() == 1, f"{badge} -> {u.locator('.nav-link .badge').inner_text()}")
        cap(u, "8-feed-detalle")

        # 6. La noticia sale en Buscar
        u.locator("nav.menu").get_by_role("link", name="Buscar").click()
        u.get_by_placeholder(re.compile("Buscar")).fill(" ".join(w for w in re.findall(r"\w+", titulo) if len(w) > 3))
        u.get_by_role("button", name="Buscar", exact=True).click()
        expect(u.get_by_text(titulo).first).to_be_visible(timeout=10000)
        check("6. la noticia de la alerta sale en Buscar", True, titulo[:60]); cap(u, "9-buscar")

        # Móvil y cierre de sesión
        m = pagina(390); m.goto(f"{APP}/login")
        m.get_by_label("Correo").fill(email); m.get_by_label("Contraseña").fill("clave-segura-1")
        m.get_by_role("button", name="Entrar").click(); expect(m).to_have_url(re.compile("/feed$"))
        expect(m.locator(".filas > li").first).to_be_visible(timeout=10000)
        check("móvil: Feed en una columna sin scroll horizontal", m.evaluate("document.documentElement.scrollWidth") <= 390)
        cap(m, "10-feed-movil")
        u.get_by_role("button", name="Cerrar sesión").click(); expect(u).to_have_url(re.compile("/login$"))
        u.goto(f"{APP}/feed"); expect(u).to_have_url(re.compile("/login$"))
        check("cerrar sesión: las rutas vuelven a Iniciar sesión", True)
        check("sin errores de JavaScript", not errores, str(errores[:3]))
        b.close()
finally:
    parar.set(); hilo.join()
print(f"   eventos vistos en RabbitMQ: {eventos}")
check("4. pasan user.preferences.updated, article.ingested y article.classified",
      eventos.get("user.preferences.updated", 0) >= 2 and eventos.get("article.ingested", 0) > 0 and eventos.get("article.classified", 0) > 0)
