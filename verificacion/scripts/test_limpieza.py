"""Al cambiar preferencias se borran las alertas NO leídas que ya no coinciden; retención de 7 días."""
import asyncio, subprocess, time
from lib import REPO, check, http, registrar, set_prefs, wait_until


def alertas(tok, uid):
    return http(tok).get("/api/notifications", params={"user_id": uid}).json()


def psql(sql):
    return subprocess.run(["docker", "exec", "newsproject-notificaciones", "sh", "-c",
                           f'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "{sql}"'], capture_output=True, text=True).stdout.strip()


async def main():
    _, tok, u = registrar(); uid = u["user_id"]; c = http(tok)
    set_prefs(tok, uid, categories=["deportes", "internacional"]); await asyncio.sleep(3)
    al = alertas(tok, uid)
    dep = [a for a in al if a["category"] == "deportes"]
    check("relleno inicial con deportes e internacional", len(al) == 20 and dep, f"{len(al)} alertas, {len(dep)} de deportes")
    leidas = dep[:2]
    for a in leidas:
        c.patch(f"/api/notifications/{a['notification_id']}/read")
    # 1) Quitar deportes
    set_prefs(tok, uid, categories=["internacional"]); await asyncio.sleep(3)
    al2 = alertas(tok, uid)
    no_leidas_dep = [a for a in al2 if a["category"] == "deportes" and not a["read"]]
    leidas_dep = {a["notification_id"] for a in al2 if a["category"] == "deportes" and a["read"]}
    check("quitar 'deportes': se borran sus alertas no leídas", not no_leidas_dep, f"quedan {len(no_leidas_dep)}")
    check("las leídas de deportes se conservan (historial)", leidas_dep == {a["notification_id"] for a in leidas})
    inter = [a for a in al2 if a["category"] == "internacional"]
    check("internacional se conserva y el relleno completa hasta 20", len(inter) == 20, f"{len(inter)}")
    # 2) Apagar una fuente
    fuentes = {s["id"]: s["name"] for s in c.get("/api/sources").json()}
    sid = next((a["source_id"] for a in inter if a.get("source_id")), None)
    check("las alertas guardan source_id", sid is not None)
    set_prefs(tok, uid, categories=["internacional"], disabled_sources=[sid]); await asyncio.sleep(3)
    al3 = alertas(tok, uid)
    check(f"apagar «{fuentes.get(sid)}»: se borran sus alertas no leídas",
          not [a for a in al3 if a.get("source_id") == sid and not a["read"]], f"{len(al3)} alertas")
    # 3) Desactivar notificaciones no borra el feed
    antes = len(al3)
    set_prefs(tok, uid, categories=["internacional"], disabled_sources=[sid], notifications_enabled=False); await asyncio.sleep(3)
    check("desactivar notificaciones no borra alertas", len(alertas(tok, uid)) == antes)
    # 4) Retención: una alerta enviada hace 8 días se borra en la limpieza
    vieja = alertas(tok, uid)[0]["notification_id"]
    psql(f"UPDATE alerts SET sent_at = now() - interval '8 days' WHERE notification_id = '{vieja}'")
    subprocess.run(["docker", "compose", "--env-file", ".env.example", "restart", "notificaciones"], cwd=REPO, capture_output=True)
    t0 = time.time()
    ok = await wait_until(lambda: psql(f"SELECT count(*) FROM alerts WHERE notification_id = '{vieja}'") == "0", 150, 5)
    check("retención: la alerta de hace 8 días se borra sola (limpieza al minuto de arrancar y cada hora)", ok,
          f"{time.time() - t0:.0f} s tras reiniciar; quedan {psql(f'SELECT count(*) FROM alerts WHERE user_id = {chr(39)}{uid}{chr(39)}')} del usuario")
    log = subprocess.run(["docker", "logs", "--since", "3m", "newsproject-notificaciones"], capture_output=True, text=True).stdout
    check("la limpieza deja su línea de log", '"stage":"cleanup.done"' in log)

asyncio.run(main())
