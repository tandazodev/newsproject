"""Genera docs/img/uml-componentes.svg (diagrama de componentes UML de la arquitectura).

Complementa a arquitectura.svg (genera_arquitectura.py): mismo sistema, en notación UML. Si cambia
un servicio, una interfaz o un tipo de comunicación, actualiza los dos generadores.

Uso: python3 docs/img/genera_uml.py && inkscape docs/img/uml-componentes.svg \\
     --export-type=png --export-filename=docs/img/uml-componentes.png --export-width=2000 --export-background=white
"""
from html import escape
from pathlib import Path

W, H = 1600, 1515
FONT = "Noto Sans, DejaVu Sans, Helvetica, Arial, sans-serif"
C = {
    # tipos de comunicación (los mismos de arquitectura.svg)
    "sinc": "#334155", "asinc": "#be185d", "rt": "#a16207", "local": "#6b7280", "int": "#6b7280",
    "texto": "#1f2937", "suave": "#6b7280", "borde": "#94a3b8", "caja": "#ffffff", "gris": "#f3f4f6",
    "nota": "#fefce8", "nota_borde": "#ca8a04",
}
TIPOS = {
    "rest": ("SÍNCRONA · REST/HTTP", "sinc"),
    "http": ("SÍNCRONA · HTTP", "sinc"),
    "amqp": ("ASÍNCRONA · AMQP", "asinc"),
    "ws": ("TIEMPO REAL · WebSocket", "rt"),
    "local": ("LOCAL · driver de BD", "local"),
    "int": ("INTERNA DEL BROKER", "int"),
}
out = []


def t(x, y, s, size=12, color=None, weight="normal", anchor="start", italic=False):
    out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color or C["texto"]}" font-weight="{weight}" '
               f'text-anchor="{anchor}"{" font-style=\"italic\"" if italic else ""}>{escape(s)}</text>')


def box(x, y, w, h, fill=None, stroke=None, r=0, dash=None, sw=1.5):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill or C["caja"]}" '
               f'stroke="{stroke or C["borde"]}" stroke-width="{sw}"{d}/>')


def icono_componente(x, y):
    """Ícono UML de componente (rectángulo con dos pestañas) con esquina superior derecha en (x, y)."""
    box(x - 18, y, 18, 22, sw=1.2, stroke=C["texto"])
    box(x - 23, y + 4, 10, 5, sw=1.2, stroke=C["texto"])
    box(x - 23, y + 13, 10, 5, sw=1.2, stroke=C["texto"])


def componente(x, y, w, h, estereotipo, nombre, detalle=(), fill=None, dash=None):
    box(x, y, w, h, fill=fill, sw=1.8, stroke=C["texto"], dash=dash)
    icono_componente(x + w - 10, y + 10)
    t(x + w / 2, y + 22, f"«{estereotipo}»", 11, C["suave"], anchor="middle", italic=True)
    t(x + w / 2, y + 42, nombre, 15, weight="bold", anchor="middle")
    for i, s in enumerate(detalle):
        t(x + w / 2, y + 62 + i * 17, s, 11, anchor="middle")


def cilindro(x, y, w, h, titulo, detalle):
    """Parte «database» dentro de un componente."""
    ry = 8
    out.append(f'<path d="M{x},{y + ry} L{x},{y + h - ry} A{w / 2},{ry} 0 0 0 {x + w},{y + h - ry} L{x + w},{y + ry}" '
               f'fill="{C["gris"]}" stroke="{C["borde"]}" stroke-width="1.4"/>')
    out.append(f'<ellipse cx="{x + w / 2}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" fill="{C["gris"]}" '
               f'stroke="{C["borde"]}" stroke-width="1.4"/>')
    t(x + w / 2, y + 30, "«database»", 10, C["suave"], anchor="middle", italic=True)
    t(x + w / 2, y + 46, titulo, 12, weight="bold", anchor="middle")
    t(x + w / 2, y + 62, detalle, 10.5, anchor="middle")


def lollipop(cx, cy, hacia="abajo", largo=20):
    """Interfaz provista: círculo en (cx, cy) unido al borde del componente."""
    dx, dy = {"abajo": (0, 1), "derecha": (1, 0), "arriba": (0, -1), "izquierda": (-1, 0)}[hacia]
    out.append(f'<line x1="{cx + dx * 8}" y1="{cy + dy * 8}" x2="{cx + dx * (8 + largo)}" y2="{cy + dy * (8 + largo)}" '
               f'stroke="{C["texto"]}" stroke-width="1.5"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="8" fill="#ffffff" stroke="{C["texto"]}" stroke-width="1.8"/>')


def dep(pts, k, sw=1.8):
    """Dependencia UML (línea punteada con punta abierta) del color de su tipo de comunicación."""
    col = C[TIPOS[k][1]]
    d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
    out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-dasharray="7 4" '
               f'marker-end="url(#abierta-{col[1:]})"/>')


def tipo(x, y, k, anchor="start"):
    txt, col = TIPOS[k]
    w = len(txt) * 5.6 + 12
    bx = x if anchor == "start" else x - w if anchor == "end" else x - w / 2
    out.append(f'<rect x="{bx:.0f}" y="{y - 10}" width="{w:.0f}" height="14" rx="7" fill="#ffffff" '
               f'stroke="{C[col]}" stroke-width="1.2"/>')
    t(bx + w / 2, y + 0.5, txt, 8.5, C[col], "bold", "middle")


def etiqueta(x, y, k, lineas, anchor="start"):
    """Tipo de comunicación + estereotipo + detalle, con fondo blanco."""
    lh = 14
    wmax = max([len(s) for s in lineas] + [len(TIPOS[k][0]) * 0.95]) * 6.1
    bx = x - 3 if anchor == "start" else x - wmax - 3 if anchor == "end" else x - wmax / 2 - 3
    out.append(f'<rect x="{bx:.0f}" y="{y - 12}" width="{wmax + 6:.0f}" height="{16 + lh * len(lineas)}" '
               f'fill="#ffffff" fill-opacity="0.92" rx="3"/>')
    tipo(x, y, k, anchor)
    for i, s in enumerate(lineas):
        t(x, y + 16 + i * lh, s, 10.5, C[TIPOS[k][1]] if i == 0 else C["suave"], "bold" if i == 0 else "normal", anchor)


def nota(x, y, w, h, lineas, titulo=None):
    """Nota UML (esquina doblada)."""
    f = 14
    out.append(f'<path d="M{x},{y} L{x + w - f},{y} L{x + w},{y + f} L{x + w},{y + h} L{x},{y + h} Z" '
               f'fill="{C["nota"]}" stroke="{C["nota_borde"]}" stroke-width="1.3"/>')
    out.append(f'<path d="M{x + w - f},{y} L{x + w - f},{y + f} L{x + w},{y + f}" fill="none" '
               f'stroke="{C["nota_borde"]}" stroke-width="1.3"/>')
    yy = y + 20
    if titulo:
        t(x + 12, yy, titulo, 11.5, weight="bold"); yy += 17
    for s in lineas:
        t(x + 12, yy, s, 10.5); yy += 15


def ancla(p1, p2):
    """Línea punteada que une una nota con su elemento."""
    out.append(f'<line x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" stroke="{C["nota_borde"]}" '
               f'stroke-width="1.2" stroke-dasharray="3 3"/>')


# ------------------------------------------------------------------ cabecera y marcadores
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="{FONT}">')
out.append("<defs>")
for col in sorted({C[TIPOS[k][1]] for k in TIPOS}):
    out.append(f'<marker id="abierta-{col[1:]}" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="9" markerHeight="9" '
               f'orient="auto-start-reverse"><path d="M1,1 L11,6 L1,11" fill="none" stroke="{col}" stroke-width="1.6"/></marker>')
out.append("</defs>")
out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
t(40, 40, "Agregador de noticias · diagrama de componentes (UML)", 22, weight="bold")
t(40, 62, "Componentes, interfaces que ofrecen (○) y dependencias entre ellos («estereotipo» y tipo de comunicación). "
  "Misma arquitectura que arquitectura.svg.", 13, C["suave"])

# ------------------------------------------------------------------ fila A: actor, frontend, medios
# Actor
ax = 110
out.append(f'<circle cx="{ax}" cy="112" r="12" fill="#ffffff" stroke="{C["texto"]}" stroke-width="1.8"/>')
for x1, y1, x2, y2 in ((ax, 124, ax, 160), (ax - 22, 136, ax + 22, 136), (ax, 160, ax - 18, 186), (ax, 160, ax + 18, 186)):
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{C["texto"]}" stroke-width="1.8"/>')
t(ax, 206, "Usuario / Administrador", 12, weight="bold", anchor="middle")
t(ax, 222, "(navegador web)", 10.5, C["suave"], anchor="middle")

componente(440, 100, 560, 120, "componente · middleware (proxy inverso)", "Frontend",
           ["SPA React + Vite servida por Nginx · :3000",
            "Nginx reenvía /api y /ws al gateway (misma red o misma PC)"])
lollipop(410, 160, "derecha", 22)
t(410, 145, "HTTP :3000", 10.5, C["suave"], anchor="middle")
dep([(140, 160), (398, 160)], "http")
etiqueta(268, 182, "http", ["«HTTP»", "páginas, /api/* y /ws/*"], "middle")

componente(1240, 100, 320, 120, "sistema externo", "Medios (internet)",
           ["feeds RSS e imágenes de portada", "las imágenes no se descargan ni guardan"], fill=C["gris"], dash="6 4")
lollipop(1480, 250, "arriba", 22)
t(1492, 262, "RSS", 10.5, C["suave"])
dep([(ax, 98), (ax, 84), (1300, 84), (1300, 98)], "http")
etiqueta(700, 79, "http", ["«HTTP GET» imágenes de portada (image_url), directo del navegador al medio"], "middle")

# ------------------------------------------------------------------ fila B: gateway
componente(300, 310, 860, 120, "componente · middleware (API Gateway)", "API Gateway",
           ["FastAPI + httpx + websockets · :8080 · sin BD · valida JWT y roles · enruta por prefijo",
            "añade X-User-Id / X-User-Role · modo distribuido: añade X-Internal-Token · 503 si el servicio cae"])
lollipop(620, 280, "abajo", 22)
t(608, 284, "IApi  /api/*", 10.5, C["suave"], anchor="end")
lollipop(900, 280, "abajo", 22)
t(912, 284, "IWebSocket  /ws/notifications", 10.5, C["suave"])
dep([(620, 222), (620, 270)], "rest")
etiqueta(612, 240, "rest", ["«REST»  Authorization: Bearer"], "end")
dep([(900, 222), (900, 270)], "ws")
etiqueta(908, 240, "ws", ["«WebSocket»  ?token=<jwt>"])

# ------------------------------------------------------------------ fila C: microservicios
SX = {"usu": 40, "not": 345, "bus": 650, "cla": 955, "ing": 1260}
SY, SW_, SH = 550, 280, 260
SERV = {
    "usu": ("Usuarios", "FastAPI :8000", "registro, login (JWT) y preferencias", ("PostgreSQL", "users · preferences")),
    "not": ("Notificaciones", "Spring Boot :8080 · Java 21", "alertas, relleno inicial y WebSocket",
            ("PostgreSQL", "prefs · alertas · artículos")),
    "bus": ("Búsqueda", "FastAPI :8000", "índice y búsqueda con y sin tildes", ("MongoDB", "articles + índice de texto")),
    "cla": ("Clasificación", "FastAPI :8000 · scikit-learn", "TF-IDF + regresión logística",
            ("PostgreSQL", "modelo · métricas · artículos")),
    "ing": ("Ingesta", "FastAPI :8000 · feedparser", "lee RSS cada 5 min · dedup. por hash", ("MongoDB", "fuentes · artículos · bitácora")),
}
for k, (nombre, tec, rol, db) in SERV.items():
    x = SX[k]
    componente(x, SY, SW_, SH, "microservicio", nombre, [tec, rol])
    cilindro(x + 50, SY + 140, SW_ - 100, 82, *db)
    out.append(f'<line x1="{x + SW_ / 2}" y1="{SY + 104}" x2="{x + SW_ / 2}" y2="{SY + 138}" stroke="{C["local"]}" '
               f'stroke-width="1.4" stroke-dasharray="3 3"/>')
    t(x + SW_ / 2 + 6, SY + 126, "«local» localhost", 9.5, C["suave"])
    t(x + SW_ / 2, SY + 248, "GET /health (sin token)", 9.5, C["suave"], anchor="middle")

# Interfaces REST de cada servicio y dependencias del gateway
IFZ = [  # (cx, nombre de la interfaz, ruta del gateway hasta el círculo, tipo, estereotipo, lado de la etiqueta)
    (180, ["/api/users", "/api/auth"], [(300, 410), (180, 410), (180, 512)], "rest", "«REST»", "end"),
    (430, ["/api/notifications"], [(430, 432), (430, 512)], "rest", "«REST»", "end"),
    (560, ["/ws?user_id="], [(560, 432), (560, 512)], "ws", "«WebSocket»", "start"),
    (790, ["/api/search", "/api/articles"], [(790, 432), (790, 512)], "rest", "«REST»", "start"),
    (1095, ["/api/categories", "/api/classify", "/api/model"], [(1095, 432), (1095, 512)], "rest", "«REST»", "end"),
    (1400, ["/api/sources"], [(1160, 390), (1400, 390), (1400, 512)], "rest", "«REST»", "start"),
]
for cx, nombre, ruta, k, est, lado in IFZ:
    lollipop(cx, 522, "abajo", 20)
    dep(ruta, k)
    dx = 8 if lado == "start" else -8
    etiqueta(cx + dx, 456, k, [est, *nombre], lado)

# Ingesta -> Medios (RSS)
dep([(1520, 550), (1520, 330), (1480, 330), (1480, 262)], "http")
etiqueta(1470, 300, "http", ["«HTTP GET»", "feeds RSS"], "end")

# ------------------------------------------------------------------ fila D: dependencias con RabbitMQ
RY = 960          # borde superior de RabbitMQ
for cx in (180, 430, 560, 790, 1015, 1150, 1400, 1247):
    lollipop(cx, RY - 28, "abajo", 20)
AMQP = [  # (x, estereotipo, detalle, y de la etiqueta, lado)
    (180, "«publica»", ["user.preferences.updated"], 840, "start"),
    (430, "«consume»", ["notificaciones.article-classified"], 896, "end"),
    (560, "«consume»", ["notificaciones.user-", "preferences-updated"], 840, "start"),
    (790, "«consume»", ["busqueda.article-classified"], 892, "start"),
    (1015, "«consume»", ["clasificacion.article-ingested"], 840, "end"),
    (1150, "«publica»", ["article.classified"], 896, "end"),
    (1400, "«publica»", ["article.ingested", "(con source_id)"], 840, "start"),
]
for x, est, det, ly, lado in AMQP:
    dep([(x, SY + SH), (x, RY - 38)], "amqp")
    etiqueta(x + (8 if lado == "start" else -8), ly, "amqp", [est, *det], lado)
# Gateway -> API de gestión de RabbitMQ (panel del administrador)
dep([(1160, 415), (1247, 415), (1247, RY - 38)], "http")
etiqueta(1253, 880, "http", ["«HTTP» monitor", "API de gestión :15672"], "start")

# ------------------------------------------------------------------ fila E: RabbitMQ
componente(40, RY, 1520, 200, "middleware orientado a mensajes (MOM)", "RabbitMQ 3.13",
           ["interfaces: IAMQP :5672 (publicar y consumir eventos) · IGestión :15672 (panel web y API)"], fill="#fafafa")


def parte(x, y, w, h, est, nombre, extra=()):
    box(x, y, w, h, sw=1.4)
    t(x + w / 2, y + 18, f"«{est}»", 10, C["suave"], anchor="middle", italic=True)
    t(x + w / 2, y + 35, nombre, 12, weight="bold", anchor="middle")
    for i, s in enumerate(extra):
        t(x + w / 2, y + 51 + i * 14, s, 10, anchor="middle")


parte(80, RY + 82, 300, 100, "exchange", "newsproject.events", ["topic · durable", "routing key = event_type"])
QS = ["clasificacion.article-ingested", "busqueda.article-classified", "notificaciones.article-classified",
      "notificaciones.user-preferences-updated"]
for i, q in enumerate(QS):
    box(560, RY + 80 + i * 26, 420, 22, sw=1.2)
    t(570, RY + 95 + i * 26, f"«queue» {q}", 10.5)
t(770, RY + 192, "quorum · durable · x-delivery-limit 3", 10, C["suave"], anchor="middle")
parte(1160, RY + 82, 360, 100, "exchange", "newsproject.dlx", ["direct → <cola>.dlq (4 colas)", "inválidos o tras 3 entregas"])
dep([(380, RY + 132), (556, RY + 132)], "int")
etiqueta(468, RY + 116, "int", ["«binding»"], "middle")
dep([(980, RY + 132), (1156, RY + 132)], "int")
etiqueta(1068, RY + 116, "int", ["«dead-letter»"], "middle")

# ------------------------------------------------------------------ fila F: rabbitmq-init y notas
componente(40, 1200, 360, 100, "componente · corre una vez", "rabbitmq-init",
           ["importa definitions.json y crea el usuario monitor", "termina con Exited (0)"], dash="6 4")
dep([(220, 1200), (220, RY + 204)], "http")
etiqueta(228, 1180, "http", ["«HTTP» API de gestión"], "start")

nota(440, 1200, 540, 125, ["pc1: Frontend, API Gateway y Usuarios · pc2: Ingesta",
                           "pc3: Clasificación y Búsqueda",
                           "pc4: RabbitMQ, rabbitmq-init y Notificaciones",
                           "Mismas dependencias, por IP y puertos publicados; cada servicio",
                           "exige X-Internal-Token (403 sin él), salvo GET /health.",
                           "Guía: docs/despliegue-distribuido.md"],
     "Modo distribuido en 4 PCs")
ancla((710, 1200), (710, RY + 200))
nota(1020, 1200, 540, 125, ["Ningún microservicio llama a otro por REST: solo eventos en RabbitMQ.",
                            "Publicar: JSON persistente con sobre común (event_id, event_type, …).",
                            "Consumir: prefetch 10, ack manual después de guardar, idempotencia",
                            "por article_id / user_id. Inválidos a la .dlq.",
                            "Contrato: docs/eventos.md"],
     "Reglas de comunicación")
ancla((1290, 1200), (1290, RY + 200))

# ------------------------------------------------------------------ fila G: leyenda
box(40, 1355, 1520, 135, fill="#fafafa", r=8, stroke="#d1d5db")
t(60, 1381, "Notación UML", 13, weight="bold")
icono_componente(84, 1393)
t(96, 1409, "componente («estereotipo»)", 10.5)
lollipop(72, 1435, "derecha", 14)
t(96, 1439, "interfaz que ofrece (lollipop)", 10.5)
out.append(f'<path d="M58,1465 L90,1465" stroke="{C["texto"]}" stroke-width="1.8" stroke-dasharray="7 4" fill="none" '
           f'marker-end="url(#abierta-{C["sinc"][1:]})"/>')
t(96, 1469, "dependencia: «usa» la interfaz", 10.5)
nota(310, 1391, 140, 34, ["nota"])
cilindro(310, 1433, 140, 50, "", "")
t(462, 1413, "nota (aclaración)", 10.5)
t(462, 1461, "«database» parte interna", 10.5)

t(660, 1381, "Tipo de comunicación (color de la flecha)", 13, weight="bold")
LEY = [
    ("rest", "petición-respuesta HTTP/JSON a través del gateway"),
    ("http", "HTTP fuera del negocio: página, RSS, imágenes, gestión"),
    ("amqp", "eventos por RabbitMQ: el emisor no espera al receptor"),
    ("ws", "conexión persistente: el servidor empuja las alertas"),
    ("local", "servicio ↔ su BD en el mismo contenedor"),
    ("int", "dentro del broker: bindings y dead-letter"),
]
for i, (k, txt) in enumerate(LEY):
    cx, cy = 660 + (i % 2) * 450, 1409 + (i // 2) * 26
    tipo(cx, cy, k)
    t(cx + 150, cy, txt, 10, C["suave"])
t(660, 1483, "En una dependencia la flecha va de quien usa a quien ofrece: «publica» y «consume» apuntan ambas a RabbitMQ.",
  10, C["suave"])

out.append("</svg>")
open(Path(__file__).with_name("uml-componentes.svg"), "w", encoding="utf-8").write("\n".join(out))
print("svg ok")
