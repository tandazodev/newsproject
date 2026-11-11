# Verificación de newsproject

Scripts de prueba del sistema completo (API por el gateway, eventos en RabbitMQ y la app con
Playwright) y el resultado de cada ejecución.

- `scripts/` — pruebas reutilizables. `lib.py` tiene lo común (eventos de ejemplo de
  `docs/eventos.md`, cliente WebSocket, registro/login de usuarios de prueba).
- `ejecuciones/<AAAA-MM-DD_HHMM>/` — una carpeta por ejecución: `informe.md`, `logs/` (salida de
  cada prueba) y `capturas/` (pantallas de Playwright).

## Pruebas

| Script | Qué comprueba |
|---|---|
| `test_auth.py` | Registro, login, JWT, permisos por rol en el gateway, WebSocket con token, `source_id` y fuentes desactivadas |
| `test_ingesta.py` | Scraping real de una fuente nueva: `article.ingested` válidos, clasificados, 0 en la DLQ, sin duplicar |
| `test_clasif_busqueda.py` | Clasificación (DLQ, idempotencia, `/api/model`) y Búsqueda (con y sin tildes, categoría, 404) |
| `test_notificaciones.py` | Filtro por preferencias, formato del WebSocket, sin duplicados, recuperación por REST, DLQ |
| `test_backfill.py`, `test_backfill_navegador.py` | Relleno inicial del feed al guardar preferencias |
| `test_limpieza.py` | Borrado de alertas no leídas al cambiar preferencias y retención de 7 días |
| `test_feed_bandeja.py` | Feed en dos paneles (escritorio y móvil) |
| `test_panel_admin.py` | Panel del sistema: `/api/admin/status`, usuario de monitoreo, servicio caído, página `/admin` |
| `demo_app.py` | Demo de la sección 11 desde la app, con un usuario y el administrador |
| `test_tolerancia.py`, `test_productores_tras_reinicio.py` | Caídas de Búsqueda, Usuarios y Notificaciones, mensaje envenenado, duplicados y reinicio de RabbitMQ |

## Cómo ejecutar

Requiere el sistema levantado (`docker compose up -d --build`) y un entorno virtual con
`aio-pika websockets httpx PyJWT playwright` (fuera del repositorio, por ejemplo en
`/tmp/newsproject-verificacion/venv`). Las pruebas de navegador usan el Chrome del sistema.

```bash
export NP_EJECUCION=$(date +%Y-%m-%d_%H%M)
cd verificacion/scripts
/tmp/newsproject-verificacion/venv/bin/python test_auth.py
```

Las credenciales salen de `.env.example` (RabbitMQ y administrador inicial). Las pruebas crean
usuarios `v-*@ejemplo.com`, que se borran con `docker compose down -v`.

## Modo distribuido

`lib.py` acepta `NP_REPO`, `NP_GATEWAY`, `NP_AMQP_URL`, `NP_ENV_FILE` y `NP_RABBITMQ_CONTAINER`;
sin ellas usa los valores del modo de una PC. Con esas variables, `test_auth`, `test_ingesta`,
`test_clasif_busqueda`, `test_notificaciones`, `test_backfill` y `test_productores_tras_reinicio`
corren contra el modo distribuido desde pc4. Pasos en
[`docs/despliegue-distribuido.md`](../docs/despliegue-distribuido.md), sección 8.6.
