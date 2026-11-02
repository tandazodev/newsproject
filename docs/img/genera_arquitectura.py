"""Genera docs/img/arquitectura.svg (diagrama detallado de la arquitectura).

La misma arquitectura en notación UML está en genera_uml.py (uml-componentes.svg): si cambia un servicio,
una ruta, un evento o un tipo de comunicación, actualiza los dos generadores.

Uso: python3 docs/img/genera_arquitectura.py && inkscape docs/img/arquitectura.svg \\
     --export-type=png --export-filename=docs/img/arquitectura.png --export-width=2000 --export-background=white
"""
from html import escape
from pathlib import Path

W, H = 1600, 1745
FONT = "Noto Sans, DejaVu Sans, Helvetica, Arial, sans-serif"
C = {
    "ing": "#2563eb",   # article.ingested
    "cla": "#ea580c",   # article.classified
    "pref": "#059669",  # user.preferences.updated
    "rest": "#4b5563",  # REST
    "ws": "#4b5563",    # WebSocket
    "mon": "#7c3aed",   # monitoreo / admin
    "ext": "#0891b2",   # internet
    "dl": "#9ca3af",    # dead-letter
    # tipos de comunicación (etiquetas sobre cada flecha)
    "t_sinc": "#334155", "t_asinc": "#be185d", "t_rt": "#a16207", "t_local": "#6b7280", "t_int": "#6b7280",
    "texto": "#1f2937", "suave": "#6b7280", "borde": "#d1d5db", "caja": "#ffffff", "gris": "#f3f4f6",
}
out = []


def t(x, y, s, size=12, color=None, weight="normal", anchor="start", italic=False):
    out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color or C["texto"]}" font-weight="{weight}" '
               f'text-anchor="{anchor}"{" font-style=\"italic\"" if italic else ""}>{escape(s)}</text>')


def lines(x, y, items, size=11, color=None, anchor="start", lh=None, weight="normal"):
    lh = lh or size + 3
    for i, s in enumerate(items):
        t(x, y + i * lh, s, size, color, weight if i == 0 else "normal", anchor)


def box(x, y, w, h, fill=None, stroke=None, r=10, dash=None, sw=1.5):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill or C["caja"]}" '
               f'stroke="{stroke or C["borde"]}" stroke-width="{sw}"{d}/>')


def path(pts, color, dash=None, start=False, end=True, sw=2):
    d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
    mk = f' marker-end="url(#a-{color[1:]})"' if end else ""
    ms = f' marker-start="url(#s-{color[1:]})"' if start else ""
    da = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da}{mk}{ms}/>')


def label(x, y, items, color, size=10.5, anchor="start", bg=True):
    """Etiqueta de flecha: primera línea en negrita y del color de la flecha, con fondo blanco."""
    lh = size + 3
    if bg:
        wmax = max(len(s) for s in items) * size * 0.56
        bx = x - 3 if anchor == "start" else x - wmax - 3 if anchor == "end" else x - wmax / 2 - 3
        out.append(f'<rect x="{bx:.0f}" y="{y - size}" width="{wmax + 6:.0f}" height="{lh * len(items) + 2}" '
                   f'fill="#ffffff" fill-opacity="0.92" rx="3"/>')
    for i, s in enumerate(items):
        t(x, y + i * lh, s, size, color if i == 0 else C["suave"], "bold" if i == 0 else "normal", anchor)


TIPOS = {
    "rest": ("SÍNCRONA · REST/HTTP", "t_sinc"),
    "http": ("SÍNCRONA · HTTP", "t_sinc"),
    "amqp": ("ASÍNCRONA · AMQP", "t_asinc"),
    "ws": ("TIEMPO REAL · WebSocket", "t_rt"),
    "local": ("LOCAL · driver de BD", "t_local"),
    "int": ("INTERNA DEL BROKER", "t_int"),
}


def tipo(x, y, k, anchor="start"):
    """Etiqueta con el tipo de comunicación de una flecha (y = línea base del texto)."""
    txt, col = TIPOS[k]
    w = len(txt) * 5.6 + 12
    bx = x if anchor == "start" else x - w if anchor == "end" else x - w / 2
    out.append(f'<rect x="{bx:.0f}" y="{y - 10}" width="{w:.0f}" height="14" rx="7" fill="#ffffff" '
               f'stroke="{C[col]}" stroke-width="1.2"/>')
    t(bx + w / 2, y + 0.5, txt, 8.5, C[col], "bold", "middle")


# ------------------------------------------------------------------ cabecera y marcadores
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="{FONT}">')
out.append("<defs>")
for col in sorted({C[k] for k in C if k not in ("texto", "suave", "borde", "caja", "gris") and not k.startswith("t_")}):
    h = col[1:]
    out.append(f'<marker id="a-{h}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
               f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    out.append(f'<marker id="s-{h}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" '
               f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
out.append("</defs>")
out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
t(40, 42, "Agregador de noticias · arquitectura de microservicios", 22, weight="bold")
t(40, 64, "9 contenedores en la red newsproject-net · los 5 servicios de negocio solo se comunican por eventos en RabbitMQ "
  "· cada flecha indica su tipo de comunicación", 13, C["suave"])

# ------------------------------------------------------------------ fila A: navegador, frontend, medios
box(40, 90, 340, 110)
lines(60, 118, ["Navegador", "usuario normal o administrador", "token JWT en localStorage (8 h)",
                "latencia = llegada − ingested_at"], 12, lh=19, weight="bold")
box(560, 90, 440, 110)
lines(580, 118, ["Frontend · React + Vite · Nginx (proxy inverso)", "contenedor frontend · :3000 (host)",
                 "Login · Registro · Feed (bandeja) · Buscar · Fuentes", "Preferencias · Panel (solo admin)"], 12, lh=19, weight="bold")
box(1260, 90, 300, 160, fill=C["gris"], dash="6 4")
lines(1280, 118, ["Medios externos (internet)", "feeds RSS: El Universo, Perfil,", "BBC Mundo, El País…",
                  "imágenes de portada", "(no se descargan ni guardan)"], 12, lh=19, weight="bold")

path([(380, 130), (558, 130)], C["rest"])
tipo(470, 104, "http", "middle")
label(470, 122, ["HTTP :3000", ], C["rest"], anchor="middle")
label(470, 150, ["/api/* y /ws/* con el JWT"], C["rest"], anchor="middle", size=9.5)
path([(558, 182), (382, 182)], C["ws"], dash="7 5")
label(470, 196, ["WebSocket: alertas en vivo"], C["ws"], anchor="middle", size=9.5)
tipo(470, 216, "ws", "middle")
path([(210, 90), (210, 80), (1410, 80), (1410, 88)], C["ext"], dash="4 4")
label(1100, 76, ["imágenes de portada (image_url): el navegador las pide directo al medio"], C["ext"], anchor="middle", size=10)
tipo(1302, 76, "http")

# ------------------------------------------------------------------ fila B: gateway
box(40, 290, 1140, 132, sw=2)
lines(60, 318, ["API Gateway (middleware de entrada) · FastAPI + httpx + websockets · contenedor gateway · :8080 (host) · sin BD",
                "Valida el JWT (HS256, JWT_SECRET) y los permisos por rol (arquitectura 7.1): sin token 401 · rol insuficiente 403",
                "Reenvía X-User-Id / X-User-Role al servicio y descarta los que mande el cliente · 503 solo en la ruta del servicio caído",
                "GET /api/status (público) y GET /api/admin/status (solo admin): /health de cada servicio + colas y DLQ",
                "Modo distribuido (4 PCs): llega a cada servicio por IP y añade X-Internal-Token; sin él responden 403"],
      12, lh=21, weight="bold")
path([(700, 200), (700, 288)], C["rest"])
label(694, 236, ["REST /api/*", "Nginx → gateway:8000", "Authorization: Bearer"], C["rest"], anchor="end")
tipo(694, 220, "rest", "end")
path([(870, 202), (870, 288)], C["ws"], dash="7 5", start=True)
label(878, 236, ["WebSocket", "/ws/notifications?token=<jwt>"], C["ws"])
tipo(878, 220, "ws")

# ------------------------------------------------------------------ fila C: microservicios
SX = {"usu": 40, "not": 345, "bus": 650, "cla": 955, "ing": 1260}
SY, SW_, SH = 520, 280, 280
SERV = {
    "usu": ("Usuarios", "Ariana", ["FastAPI :8000", "registro (bcrypt) y login (JWT)", "roles admin/usuario · preferencias"],
            ["PostgreSQL", "users · preferences"]),
    "not": ("Notificaciones", "Ariel", ["Spring Boot :8080 · Java 21", "cruza artículos × preferencias",
                                       "alertas, relleno y WebSocket"], ["PostgreSQL", "prefs · alertas · artículos (7 días)"]),
    "bus": ("Búsqueda", "Fabricio", ["FastAPI :8000", "indexa los artículos clasificados", "búsqueda con y sin tildes"],
            ["MongoDB", "articles + índice de texto"]),
    "cla": ("Clasificación", "Fabricio", ["FastAPI :8000 · scikit-learn", "TF-IDF + regresión logística",
                                         "categoría · tags · score"], ["PostgreSQL", "modelo · métricas · artículos"]),
    "ing": ("Ingesta", "Kevin", ["FastAPI :8000 · feedparser", "lee RSS cada 5 min y limpia HTML",
                                 "dedup. por hash · id UUID v5"], ["MongoDB", "fuentes · artículos · bitácora"]),
}
for k, (nombre, dueno, api, db) in SERV.items():
    x = SX[k]
    box(x, SY, SW_, SH, sw=2)
    t(x + SW_ / 2, SY + 28, nombre, 15, weight="bold", anchor="middle")
    t(x + SW_ / 2, SY + 46, f"{dueno} · un contenedor con backend + BD", 10.5, C["suave"], anchor="middle")
    box(x + 15, SY + 58, SW_ - 30, 92, r=8)
    lines(x + SW_ / 2, SY + 80, api, 11.5, anchor="middle", lh=22, weight="bold")
    path([(x + SW_ / 2, SY + 150), (x + SW_ / 2, SY + 178)], C["suave"], sw=1.5)
    t(x + SW_ / 2 + 6, SY + 168, "localhost · local", 9.5, C["suave"])
    box(x + 15, SY + 180, SW_ - 30, 82, fill=C["gris"], r=8)
    lines(x + SW_ / 2, SY + 206, db, 11.5, anchor="middle", lh=22, weight="bold")


# Gateway -> servicios (REST)
def rest(x, lab):
    path([(x, 422), (x, 518)], C["rest"])
    tipo(x + 6, 440, "rest")
    label(x + 6, 457, lab, C["rest"])

rest(150, ["/api/users · /api/auth", "registro · login · /me", "preferencias (PUT)"])
rest(420, ["/api/notifications", "listar · ?unread=true", "PATCH /{id}/read"])
path([(585, 518), (585, 424)], C["ws"], dash="7 5", start=True)
tipo(590, 478, "ws")
label(590, 495, ["WS /ws?user_id=", "(user_id del JWT)"], C["ws"])
rest(740, ["/api/search", "/api/articles/{id}"])
rest(1015, ["/api/categories", "/api/classify", "/api/model"])
path([(1180, 372), (1330, 372), (1330, 518)], C["rest"])
tipo(1338, 440, "rest")
label(1338, 457, ["/api/sources", "listar: todos", "alta y scrape: admin"], C["rest"])
path([(1480, 518), (1480, 252)], C["ext"], dash="4 4")
tipo(1475, 276, "http", "end")
label(1475, 293, ["GET feeds RSS", "httpx · cada 5 min", "y manual (admin)"], C["ext"], anchor="end")

# Gateway -> RabbitMQ (monitoreo)
path([(1180, 405), (1247, 405), (1247, 958)], C["mon"], dash="8 4")

# ------------------------------------------------------------------ fila D: publicar / consumir
def pub(x, color, lab, ly, anchor="start", dx=6):
    path([(x, 800), (x, 958)], color, sw=2.5)
    tipo(x + (dx if anchor == "start" else -dx), ly - 17, "amqp", anchor)
    label(x + (dx if anchor == "start" else -dx), ly, lab, color, anchor=anchor)

def con(x, color, lab, ly, anchor="start", dx=6):
    path([(x, 958), (x, 802)], color, sw=2.5)
    tipo(x + (dx if anchor == "start" else -dx), ly - 17, "amqp", anchor)
    label(x + (dx if anchor == "start" else -dx), ly, lab, color, anchor=anchor)

pub(180, C["pref"], ["publica user.preferences.updated", "al guardar preferencias"], 838)
con(420, C["cla"], ["consume", "notificaciones.article-classified"], 908, anchor="end")
con(560, C["pref"], ["consume", "notificaciones.user-", "preferences-updated"], 896)
con(780, C["cla"], ["consume", "busqueda.article-classified"], 866)
con(1015, C["ing"], ["consume", "clasificacion.", "article-ingested"], 838)
pub(1175, C["cla"], ["publica", "article.classified"], 908, anchor="end")
tipo(1253, 829, "http")
label(1253, 846, ["API de gestión :15672", "usuario monitor", "(solo lectura) → panel"], C["mon"])
pub(1410, C["ing"], ["publica", "article.ingested", "(con source_id)"], 838)

# ------------------------------------------------------------------ fila E: RabbitMQ
box(40, 960, 1520, 370, fill="#fafafa", sw=2)
t(60, 990, "RabbitMQ 3.13 · middleware orientado a mensajes (MOM) · contenedor rabbitmq · AMQP :5672 · gestión :15672 (panel web y API)", 15, weight="bold")
t(60, 1009, "Publicar: JSON persistente con sobre común (event_id, event_type, occurred_at, version, payload). "
  "Consumir: prefetch 10 · ack manual después de guardar · idempotencia por article_id / user_id.", 10.5, C["suave"])
box(70, 1030, 330, 270, fill=C["gris"])
lines(235, 1080, ["newsproject.events", "exchange topic · durable", "routing key = event_type", "",
                  "article.ingested", "article.classified", "user.preferences.updated"], 13, anchor="middle", lh=24, weight="bold")
QY = [1040, 1105, 1170, 1235]
QS = [("clasificacion.article-ingested", C["ing"], "article.ingested"),
      ("busqueda.article-classified", C["cla"], "article.classified"),
      ("notificaciones.article-classified", C["cla"], "article.classified"),
      ("notificaciones.user-preferences-updated", C["pref"], "user.preferences.updated")]
for y, (nombre, col, rk) in zip(QY, QS):
    out.append(f'<rect x="600" y="{y}" width="430" height="50" rx="6" fill="#ffffff" stroke="{C["borde"]}" stroke-width="1.5"/>')
    out.append(f'<rect x="600" y="{y}" width="7" height="50" rx="2" fill="{col}"/>')
    t(620, y + 22, nombre, 13, weight="bold")
    t(620, y + 40, "cola quorum · durable · x-delivery-limit 3", 10.5, C["suave"])
    path([(400, y + 25), (598, y + 25)], col, sw=2)
    label(500, y + 18, [f"binding: {rk}"], col, anchor="middle", size=10)
    path([(1030, y + 25), (1178, y + 25)], C["dl"], dash="2 4", sw=2)
    label(1104, y + 18, ["dead-letter (interno)"], C["suave"], anchor="middle", size=9.5)
box(1180, 1030, 350, 270, fill=C["gris"])
lines(1355, 1062, ["newsproject.dlx", "exchange direct → <cola>.dlq"], 13, anchor="middle", lh=22, weight="bold")
for i, (nombre, _, _) in enumerate(QS):
    t(1200, 1122 + i * 22, f"{nombre}.dlq", 11)
lines(1200, 1222, ["Va a la .dlq: mensaje inválido (JSON roto o", "campo obligatorio ausente) de inmediato, o",
                   "error transitorio tras 3 entregas fallidas."], 10.5, C["suave"], lh=16)

# ------------------------------------------------------------------ fila F: rabbitmq-init, leyenda
box(40, 1370, 380, 92, fill=C["gris"], dash="6 4")
lines(60, 1396, ["rabbitmq-init · curl (corre una vez)", "importa infra/rabbitmq/definitions.json",
                 "crea el usuario monitor (etiqueta monitoring)", "y termina con Exited (0)"], 11.5, lh=18, weight="bold")
path([(230, 1370), (230, 1332)], C["mon"], dash="8 4")
label(236, 1356, ["POST /api/definitions · PUT /api/users/monitor"], C["mon"], size=10)
tipo(510, 1356, "http")

LX, LY = 480, 1380
legend = [
    (C["ing"], None, "article.ingested (Ingesta → Clasificación)"),
    (C["cla"], None, "article.classified (Clasificación → Búsqueda y Notificaciones)"),
    (C["pref"], None, "user.preferences.updated (Usuarios → Notificaciones)"),
    (C["rest"], None, "REST síncrono vía gateway (HTTP/JSON)"),
    (C["ws"], "7 5", "WebSocket en tiempo real"),
    (C["mon"], "8 4", "administración y monitoreo de RabbitMQ"),
    (C["ext"], "4 4", "internet (feeds RSS e imágenes)"),
    (C["dl"], "2 4", "dead-letter a la .dlq"),
]
for i, (col, dash, txt) in enumerate(legend):
    cx = LX + (i % 2) * 540
    cy = LY + (i // 2) * 24
    path([(cx, cy), (cx + 44, cy)], col, dash=dash, end=False, sw=2.5)
    t(cx + 54, cy + 4, txt, 11.5)
t(480, 1492, "Flecha hacia RabbitMQ: el servicio publica en newsproject.events. Flecha desde RabbitMQ: el servicio consume su cola.", 11, C["suave"])
t(480, 1510, "Ningún servicio de negocio llama a otro por REST; el frontend solo habla con el gateway (vía Nginx).", 11, C["suave"])
t(480, 1528, "Cada servicio expone GET /health con formato común (checks.db, checks.rabbitmq, details); su BD solo escucha en localhost.", 11, C["suave"])
t(480, 1546, "Fuente editable: docs/img/arquitectura.svg · contrato: docs/eventos.md y docs/arquitectura.md (secciones 5 a 7).", 11, C["suave"])

# ------------------------------------------------------------------ fila G: tipos de comunicación
box(40, 1580, 1520, 140, fill="#fafafa")
t(60, 1606, "Tipos de comunicación (etiqueta sobre cada flecha)", 14, weight="bold")
TIPO_TXT = [
    ("rest", "petición-respuesta HTTP/JSON: quien llama espera la respuesta (navegador → Nginx → gateway → servicio)"),
    ("http", "petición-respuesta fuera del flujo de negocio: página, feeds RSS, imágenes, gestión de RabbitMQ"),
    ("amqp", "eventos vía RabbitMQ (middleware orientado a mensajes): el emisor no espera al receptor"),
    ("ws", "conexión persistente y bidireccional: Notificaciones empuja cada alerta al navegador sin que la pida"),
    ("local", "cada servicio con su BD dentro del mismo contenedor (localhost); ningún otro servicio llega a ella"),
    ("int", "movimientos dentro de RabbitMQ: bindings del exchange a las colas y dead-letter a las .dlq"),
]
for i, (k, txt) in enumerate(TIPO_TXT):
    cx, cy = 60 + (i % 2) * 750, 1634 + (i // 2) * 24
    tipo(cx, cy, k)
    t(cx + 205, cy, txt, 10.5, C["suave"])
t(60, 1710, "Middleware: Nginx (proxy inverso), API Gateway (autenticación, permisos y enrutamiento) y RabbitMQ (mensajería asíncrona). "
  "Modo distribuido en 4 PCs: docs/despliegue-distribuido.md.", 10.5, C["suave"])

out.append("</svg>")
open(Path(__file__).with_name("arquitectura.svg"), "w", encoding="utf-8").write("\n".join(out))
print("svg ok")
