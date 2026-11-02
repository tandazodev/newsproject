"""Feed en dos paneles: altura fija, pestañas, selección/leída, alerta en vivo, móvil."""
import asyncio, re, threading, uuid
from playwright.sync_api import expect, sync_playwright
from lib import CAPTURAS, check, classified_example, envelope, publish
APP = "http://localhost:3000"

def registrar(pg, cats):
    tag = uuid.uuid4().hex[:5]
    pg.goto(f"{APP}/registro")
    pg.get_by_label("Nombres").fill("Sofía"); pg.get_by_label("Apellidos").fill("Ramírez Vega")
    pg.get_by_label("Username").fill(f"sofia.{tag}"); pg.get_by_label("Correo").fill(f"sofia.{tag}@ejemplo.com")
    pg.get_by_label("Contraseña", exact=True).fill("clave-segura-1"); pg.get_by_label("Repite la contraseña").fill("clave-segura-1")
    pg.get_by_role("button", name="Crear cuenta").last.click()
    expect(pg).to_have_url(re.compile(r"/preferencias\?nuevo=1$"))
    for c in cats: pg.get_by_label(c).check()
    pg.get_by_role("button", name="Guardar preferencias").click()
    expect(pg).to_have_url(re.compile("/feed$")); expect(pg.get_by_text("En vivo")).to_be_visible(timeout=15000)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    errores = []
    pg = b.new_context(viewport={"width": 1280, "height": 900}, locale="es-EC").new_page()
    pg.on("pageerror", lambda e: errores.append(str(e)))
    registrar(pg, ["Internacional", "Deportes"])
    filas = pg.locator(".filas > li")
    expect(filas).to_have_count(20, timeout=10000)
    alto = lambda: pg.evaluate("document.documentElement.scrollHeight")
    h0 = alto()
    check("escritorio: la página cabe en una pantalla (900 px)", h0 <= 900, f"scrollHeight={h0}")
    check("pestaña 'Nuevas (20)' y lista con scroll propio",
          pg.get_by_role("tab", name="Nuevas (20)").count() == 1
          and pg.evaluate("(() => { const u = document.querySelector('.filas'); return u.scrollHeight > u.clientHeight; })()"))
    primero = filas.nth(0).locator(".fila-titulo").inner_text()
    check("el detalle muestra la primera sin marcarla leída",
          pg.locator(".detalle-titulo").inner_text() == primero and pg.locator(".nav-link .badge").inner_text() == "20")
    tercera = filas.nth(2).locator(".fila-titulo").inner_text()
    filas.nth(2).locator("button").click()
    expect(pg.locator(".detalle-titulo")).to_have_text(tercera)
    expect(pg.locator(".nav-link .badge")).to_have_text("19")
    check("elegir una alerta: detalle + leída (contador 20 -> 19) y sigue en la lista",
          filas.count() == 20 and "fila-activa" in filas.nth(2).locator("button").get_attribute("class"))
    check("detalle con enlace a la fuente y 'Ya publicada'",
          pg.get_by_role("link", name=re.compile("Leer en la fuente original")).count() == 1
          and pg.locator(".detalle .latencia").inner_text() == "Ya publicada")
    pg.screenshot(path=str(CAPTURAS / "feed-bandeja-escritorio.png"))
    # alerta en vivo
    art = classified_example(category="deportes", title=f"Gol en el último minuto {uuid.uuid4().hex[:4]}", image_url=None)
    h = threading.Thread(target=lambda: asyncio.run(publish(envelope("article.classified", art)))); h.start(); h.join()
    expect(filas.nth(0).locator(".fila-titulo")).to_have_text(art["title"], timeout=10000)
    check("alerta en vivo entra arriba de 'Nuevas' con su latencia, sin crecer la página",
          re.search(r"\d", filas.nth(0).locator(".fila-latencia").inner_text()) is not None and alto() == h0,
          f"{filas.nth(0).locator('.fila-latencia').inner_text()}, scrollHeight={alto()}")
    # pestañas
    pg.get_by_role("tab", name="Leídas").click()
    check("pestaña 'Leídas': la que se abrió", filas.count() == 1 and filas.nth(0).locator(".fila-titulo").inner_text() == tercera)
    check("solo dos pestañas: Nuevas y Leídas (sin 'Publicadas')",
          pg.get_by_role("tab").count() == 2 and pg.get_by_role("tab", name="Publicadas").count() == 0)
    pg.get_by_role("tab", name=re.compile("^Nuevas")).click()
    check("al volver a 'Nuevas' ya no está la leída", filas.count() == 20, f"{filas.count()}")
    # móvil
    m = b.new_context(viewport={"width": 390, "height": 800}, locale="es-EC").new_page()
    m.on("pageerror", lambda e: errores.append(str(e)))
    registrar(m, ["Internacional"])
    mf = m.locator(".filas > li"); expect(mf.first).to_be_visible(timeout=10000)
    check("móvil: solo la lista, sin scroll horizontal", not m.locator(".bandeja-detalle").is_visible()
          and m.evaluate("document.documentElement.scrollWidth") <= 390)
    m.screenshot(path=str(CAPTURAS / "feed-bandeja-movil-lista.png"))
    mf.nth(1).locator("button").click()
    expect(m.locator(".detalle-titulo")).to_be_visible()
    check("móvil: tocar abre el detalle y oculta la lista", not m.locator(".bandeja-lista").is_visible())
    m.screenshot(path=str(CAPTURAS / "feed-bandeja-movil-detalle.png"))
    m.get_by_role("button", name="← Volver").click()
    check("móvil: '← Volver' regresa a la lista", m.locator(".bandeja-lista").is_visible())
    check("sin errores de JavaScript", not errores, str(errores[:2]))
    b.close()
