"""Usuario nuevo: el feed se construye al guardar preferencias, sin scrapear."""
import re, time, uuid
from playwright.sync_api import expect, sync_playwright
from lib import CAPTURAS, check
APP = "http://localhost:3000"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_context(viewport={"width": 1280, "height": 900}, locale="es-EC").new_page()
    errores = []; pg.on("pageerror", lambda e: errores.append(str(e)))
    tag = uuid.uuid4().hex[:5]
    pg.goto(f"{APP}/registro")
    pg.get_by_label("Nombres").fill("Mateo"); pg.get_by_label("Apellidos").fill("Salinas Ochoa")
    pg.get_by_label("Username").fill(f"mateo.{tag}"); pg.get_by_label("Correo").fill(f"mateo.{tag}@ejemplo.com")
    pg.get_by_label("Contraseña", exact=True).fill("clave-segura-1"); pg.get_by_label("Repite la contraseña").fill("clave-segura-1")
    pg.get_by_role("button", name="Crear cuenta").last.click()
    expect(pg).to_have_url(re.compile(r"/preferencias\?nuevo=1$"))
    pg.get_by_label("Internacional").check()
    t0 = time.time()
    pg.get_by_role("button", name="Guardar preferencias").click()
    expect(pg).to_have_url(re.compile("/feed$"))
    alertas = pg.locator(".filas > li")
    expect(alertas.first).to_be_visible(timeout=10000)
    pg.wait_for_timeout(1500)
    n = pg.locator(".nav-link .badge").inner_text()
    check("feed construido al guardar preferencias, sin scrapear", alertas.count() == 20 and n == "20",
          f"{alertas.count()} visibles, contador {n}, {time.time() - t0:.1f}s desde Guardar")
    etiquetas = set(pg.locator(".filas .fila-latencia").all_inner_texts())
    check("las alertas del relleno dicen 'publicada' (detalle: 'Ya publicada')", etiquetas == {"publicada"}
          and pg.locator(".detalle .latencia").inner_text() == "Ya publicada", str(etiquetas))
    cats = set(pg.locator(".filas .feed-categoria").all_inner_texts())
    check("solo de su categoría (Internacional)", cats == {"Internacional"}, str(cats))
    pg.screenshot(path=str(CAPTURAS / "backfill-feed-usuario-nuevo.png"))
    check("sin errores de JavaScript", not errores, str(errores[:2]))
    b.close()
