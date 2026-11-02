# Documento de Arquitectura – Agregador de Noticias (v3)

Actualizado el 01/11/2026 · Fabricio Josue Ruiz Aguilar · versión editable: https://claude.ai/artifact/N3raGZTxeEY26hnUBe1fVx

## 1. Introducción y alcance

El sistema obtiene noticias de fuentes externas, las clasifica, las vuelve buscables y notifica en tiempo real a cada usuario según sus preferencias. Lo hacen cinco microservicios desacoplados por RabbitMQ, más un API Gateway y un frontend React. Esta versión reemplaza a la del 21/10/2026 y adopta el contrato de eventos del repositorio ([`docs/eventos.md`](eventos.md)) como única fuente de verdad.

**Flujo extremo a extremo:** Ingesta obtiene un artículo y publica `article.ingested` → Clasificación lo etiqueta y publica `article.classified` → Búsqueda lo indexa y Notificaciones lo cruza con las preferencias de los usuarios → el frontend recibe la alerta por WebSocket sin recargar. En paralelo, Usuarios publica `user.preferences.updated` cada vez que alguien cambia sus intereses.

**Principios de diseño**

- Cada microservicio de negocio empaqueta su backend y su propia base de datos en un mismo contenedor; la BD solo escucha dentro de ese contenedor, así ningún servicio puede leer la BD de otro.
- Los procesos asíncronos se comunican solo por eventos en RabbitMQ, nunca con llamadas REST entre servicios.
- El frontend consume REST a través de un único API Gateway y recibe cambios en vivo por WebSocket.
- Cada servicio vive en su carpeta, con su Dockerfile, y corre en su propio contenedor.
- Todo el sistema se levanta con un solo comando: `docker compose up`.
- Un servicio caído no pierde mensajes ni detiene a los demás: colas durables, mensajes persistentes, `ack` manual y cola de mensajes fallidos (DLQ).

**Alcance:** ingesta, clasificación, búsqueda, usuarios, notificaciones, gateway y frontend, con registro e inicio de sesión por correo y contraseña, dos roles (administrador y usuario) y un token JWT que valida el gateway (sección 7.1). Quedan fuera OAuth y el inicio de sesión con terceros, la recuperación de contraseña y el despliegue en la nube.

## 2. Diagrama de arquitectura

![Diagrama de arquitectura del Agregador de Noticias](img/arquitectura.png)

El diagrama muestra los 9 contenedores y **cada flecha lleva su detalle** (ruta, evento o cola). Fuente editable: [`img/arquitectura.svg`](img/arquitectura.svg), generada con `img/genera_arquitectura.py`.

- **Navegador → Frontend → Gateway:** el navegador solo habla con Nginx (`:3000`), que reenvía `/api/*` (REST con `Authorization: Bearer <jwt>`) y `/ws/*` (WebSocket con `?token=<jwt>`) al gateway. Las imágenes de portada las pide el navegador directo al medio.
- **Gateway → servicios (gris):** valida el JWT y los permisos (sección 7.1) y enruta por prefijo; cada flecha indica las rutas de ese servicio. Con Notificaciones además mantiene el WebSocket interno (`/ws?user_id=` tomado del token). Para el panel del administrador consulta la API de gestión de RabbitMQ con un usuario de solo monitoreo (morado).
- **Servicios ↔ RabbitMQ (colores por evento):** flecha hacia RabbitMQ = el servicio publica en `newsproject.events`; desde RabbitMQ = consume su cola (prefetch 10, `ack` manual). Dentro de RabbitMQ, cada *binding* lleva el evento a su cola y un mensaje inválido o que falla 3 veces pasa a su `.dlq` por `newsproject.dlx`.
- **Cada caja de servicio** es un contenedor con su backend y su BD, que solo escucha en `localhost`. Ingesta es el único que sale a internet (feeds RSS cada 5 minutos); `rabbitmq-init` carga la topología y crea el usuario de monitoreo al arrancar.

## 3. Microservicios, bases de datos y responsables

Son cinco microservicios de negocio, cada uno con su backend y su base de datos dentro del mismo contenedor, más el gateway, el frontend y el broker. Usuarios se separa de Notificaciones para que cada servicio tenga una sola responsabilidad: si Usuarios cae, Notificaciones sigue enviando alertas con su copia local de las preferencias.

| Servicio (carpeta) | Responsabilidad | Stack | Base de datos propia (mismo contenedor) | Publica | Consume | Responsable |
| --- | --- | --- | --- | --- | --- | --- |
| Ingesta (`ingesta/`) | Lee feeds RSS y sitios web, limpia el texto, deduplica y publica artículos | Python 3.12+ · FastAPI · feedparser · BeautifulSoup4 | MongoDB: fuentes, artículos crudos y bitácora de scraping | `article.ingested` | — | Kevin |
| Clasificación (`clasificacion/`) | Asigna categoría, etiquetas y puntaje de confianza | Python · FastAPI · scikit-learn (TF-IDF + Naive Bayes o regresión logística) | PostgreSQL: categorías, versiones del modelo con sus métricas y artículos clasificados | `article.classified` | `article.ingested` | Fabricio |
| Búsqueda (`busqueda/`) | Indexa artículos clasificados y atiende consultas de texto | Python · FastAPI | MongoDB con índice de texto | — | `article.classified` | Fabricio |
| Usuarios (`usuarios/`) | Registro, inicio de sesión (emite el JWT), roles y gestión de preferencias | Python · FastAPI · bcrypt · PyJWT | PostgreSQL: usuarios (con hash de contraseña y rol) y preferencias | `user.preferences.updated` | — | Ariana |
| Notificaciones (`notificaciones/`) | Cruza artículos con preferencias, guarda alertas y las emite por WebSocket | Java 21 · Spring Boot | PostgreSQL: copia de preferencias, copia de los artículos clasificados de los últimos 7 días y alertas | — | `article.classified`, `user.preferences.updated` | Ariel |
| API Gateway (`gateway/`) | Punto de entrada único: valida el JWT y los permisos, enruta REST y reenvía el WebSocket | Python · FastAPI · httpx · websockets | Sin BD (sin estado) | — | — | Ariana |
| Frontend (`frontend/`) | SPA: login y registro, feed en vivo (bandeja Nuevas/Leídas), búsqueda, fuentes (alta y scraping para el admin; encender o apagar en mi feed para todos), preferencias y panel del sistema (solo admin) | React · Vite, servido con Nginx | Sin BD | — | — | Todo el grupo |
| RabbitMQ | Broker de mensajes | `rabbitmq:3.13-management` | Volumen de persistencia | — | — | Todo el grupo |

Los servicios solo comparten contratos de eventos (sección 5) y de REST (sección 7), por eso cada integrante puede usar su lenguaje. El informe debe reflejar que Notificaciones está en Java y no en Python.

### 3.1 Método de clasificación: TF-IDF + clasificador supervisado

Clasificación usa un modelo de scikit-learn entrenado con noticias ya etiquetadas en las 8 categorías de la sección 5.4; no usa reglas manuales de palabras clave.

1. **Dataset:** noticias en español etiquetadas por la sección de su feed (sección 3.2). Se entrena con todas menos las del conjunto de prueba revisado a mano, que se reserva para evaluar.
2. **Vectorización:** `TfidfVectorizer` sobre título + cuerpo, con stopwords en español, unigramas y bigramas.
3. **Clasificador:** se entrenan `MultinomialNB` y `LogisticRegression` en un `Pipeline` y se comparan con validación cruzada; se queda el de mayor F1 macro.
4. **Evaluación:** precisión, exhaustividad (recall) y F1 por categoría y macro, más la matriz de confusión; estos valores van a los resultados del informe.
5. **Despliegue:** el script `clasificacion/train.py` entrena fuera de línea y guarda el pipeline con `joblib` (`model.joblib`); el servicio lo carga al arrancar y registra su versión y métricas en su BD.
6. **Inferencia por evento:** `category` = clase con mayor probabilidad (`predict_proba`), `score` = esa probabilidad. Si `score` es menor que un umbral configurable (`MIN_SCORE`, inicial 0.5), la categoría es `otros`.
7. **Etiquetas:** `tags` = los 5 términos con mayor peso TF-IDF del artículo, normalizados en minúsculas y con guiones.

### 3.2 Cómo se obtiene el dataset

Las etiquetas no se ponen a mano: salen de la **sección** del medio. Todo lo publicado en el feed de deportes de un periódico se etiqueta `deportes`.

| Pieza | Ubicación | Qué hace |
| --- | --- | --- |
| Lista de feeds | `clasificacion/data/feeds.csv` | 35 feeds por sección con su categoría y país (`EC`, `ES`, `AR`): El Universo y Ecuavisa (Ecuador), El País (España) y Perfil (Argentina) |
| Recolector | `clasificacion/tools/collect_dataset.py` | Lee los feeds, arma el texto y agrega cada noticia nueva al CSV sin duplicar (compara por URL normalizada). `--check` prueba los feeds y muestra títulos de ejemplo |
| Ejecución periódica | `.github/workflows/dataset.yml` | GitHub Actions corre el recolector cada hora, aunque nadie tenga la PC encendida |
| Dataset acumulado | rama `dataset` del repositorio (`dataset.csv`) | Fuera de `main`, para no ensuciar el historial; `.gitignore` excluye `dataset.csv` de las demás ramas |

- **Plazo:** el grupo deja correr la recolección unos 5 días antes de entrenar el modelo final; mientras tanto se entrena un modelo provisional con lo acumulado.
- **Categoría `otros`:** no se recolecta; la asigna el servicio cuando la confianza es menor que `MIN_SCORE`.
- **Conjunto de prueba:** `collect_dataset.py --sample-test N` toma la misma cantidad por categoría y, dentro de cada una, mezcla noticias ecuatorianas y extranjeras (`--local-share`, por defecto 50 %). El grupo revisa a mano la columna `category_revisada`; sobre ese conjunto se miden precisión, recall y F1.
- **Riesgos conocidos:** algunas categorías dependen de una sola fuente extranjera (salud y tecnología, de Perfil), lo que puede hacer que el modelo aprenda el medio en vez del tema; y los feeds por sección traen algo de ruido (notas de otra temática). Ambos se controlan con la mezcla del conjunto de prueba y midiendo el F1 por categoría.

**Compatibilidad con Ingesta.** El modelo solo clasifica bien si en producción recibe textos armados igual que al entrenar. Por eso Ingesta copia tal cual de `collect_dataset.py` las funciones `normalize_url`, `clean_html` y `entry_text`; su `body` es solo el contenido del feed (sin descargar la página), y Clasificación predice sobre `title + ". " + body`. Si esas funciones cambian, se cambian en ambos lados en el mismo pull request.

## 4. Comunicación síncrona, asíncrona y en tiempo real

Las consultas del usuario son síncronas (REST), todo el procesamiento de artículos y preferencias es asíncrono (RabbitMQ) y las alertas en vivo viajan por WebSocket.

| Tipo | Protocolo | Entre quiénes | Ejemplos |
| --- | --- | --- | --- |
| Síncrona | REST (HTTP/JSON) | Frontend → Gateway → Ingesta, Clasificación, Búsqueda, Usuarios, Notificaciones | `GET /api/search?q=`, `PUT /api/users/{id}/preferences`, `POST /api/sources/{id}/scrape` |
| Asíncrona | RabbitMQ (AMQP 0-9-1) | Ingesta → Clasificación → Búsqueda y Notificaciones; Usuarios → Notificaciones | `article.ingested`, `article.classified`, `user.preferences.updated` |
| Tiempo real | WebSocket | Notificaciones → Gateway → Frontend | `/ws/notifications?token=<jwt>`: el artículo aparece sin recargar |

**Reglas de comunicación**

1. Ningún servicio llama a otro por REST dentro de un flujo asíncrono; solo publica o consume eventos.
2. Las colas son durables y los mensajes persistentes (`delivery_mode: 2`); el consumidor hace `ack` solo después de procesar y guardar.
3. Un mensaje que falla 3 veces pasa a su DLQ y no bloquea la cola principal (sección 5.5).
4. Los consumidores son idempotentes: procesar dos veces el mismo artículo no genera duplicados.
5. El frontend nunca habla con RabbitMQ ni con las bases de datos; solo con el gateway.
6. Cada servicio reintenta la conexión al broker y a su BD al arrancar, con espera creciente.

## 5. Topología RabbitMQ y contratos de eventos

Un exchange `topic` (`newsproject.events`) reparte tres eventos a cuatro colas, una por consumidor y por evento. Cada cola tiene su DLQ, alimentada por el exchange `newsproject.dlx`. La topología se carga sola al arrancar desde `infra/rabbitmq/definitions.json`.

### 5.1 Exchanges, colas y routing keys

| Cola | Routing key | Productor | Consumidor | DLQ |
| --- | --- | --- | --- | --- |
| `clasificacion.article-ingested` | `article.ingested` | Ingesta | Clasificación | `clasificacion.article-ingested.dlq` |
| `busqueda.article-classified` | `article.classified` | Clasificación | Búsqueda | `busqueda.article-classified.dlq` |
| `notificaciones.article-classified` | `article.classified` | Clasificación | Notificaciones | `notificaciones.article-classified.dlq` |
| `notificaciones.user-preferences-updated` | `user.preferences.updated` | Usuarios | Notificaciones | `notificaciones.user-preferences-updated.dlq` |

- Exchange principal: `newsproject.events`, tipo `topic`, durable.
- Exchange de mensajes fallidos: `newsproject.dlx`, tipo `direct`, durable; enruta a cada `.dlq` por su nombre.
- Las colas principales son de tipo **quorum** con `x-delivery-limit: 3`, `x-dead-letter-exchange: newsproject.dlx` y `x-dead-letter-routing-key: <cola>.dlq`.
- Las routing keys siguen el formato `<entidad>.<acción en pasado>`: un evento describe algo que ya ocurrió.
- Las dos colas de `article.classified` reciben cada una su propia copia del mensaje; agregar un consumidor nuevo no obliga a cambiar a Clasificación.

### 5.2 Sobre común (envelope)

Todos los mensajes comparten este envoltorio, en JSON UTF-8 con `content_type: application/json`. El contenido específico va en `payload`.

```json
{
  "event_id": "b7c1f6de-4a0e-4d2a-9d1e-3f6a2c8e9a10",
  "event_type": "article.ingested",
  "occurred_at": "2026-10-25T14:30:00Z",
  "version": 1,
  "payload": { }
}
```

| Campo | Tipo | Notas |
| --- | --- | --- |
| `event_id` | UUID v4 | Único por mensaje; sirve para trazas y para descartar reentregas del mismo mensaje |
| `event_type` | string | Igual a la routing key |
| `occurred_at` | ISO 8601 UTC | Momento en que el productor publicó; base para medir latencia |
| `version` | entero | Versión del esquema del `payload`; sube solo con cambios incompatibles |
| `payload` | objeto | Ver 5.3 |

### 5.3 Eventos

**`article.ingested`** — publica Ingesta, consume Clasificación.

```json
{
  "event_id": "b7c1f6de-4a0e-4d2a-9d1e-3f6a2c8e9a10",
  "event_type": "article.ingested",
  "occurred_at": "2026-10-25T14:30:00Z",
  "version": 1,
  "payload": {
    "article_id": "5f2a9c1e-8d3b-5c7a-b1e2-0a9d4e6f7c31",
    "url": "https://ejemplo.com/noticia-1",
    "title": "Título de la noticia",
    "body": "Texto limpio del artículo...",
    "source": "ejemplo.com",
    "source_id": "6ae7aeea22e26d7d67be2610",
    "published_at": "2026-10-25T13:55:00Z",
    "image_url": "https://ejemplo.com/fotos/noticia-1.jpg",
    "hash": "sha256-del-titulo-y-cuerpo"
  }
}
```

| Campo | Tipo | Notas |
| --- | --- | --- |
| `article_id` | UUID v5 | Se calcula a partir de la URL normalizada: la misma noticia scrapeada dos veces tiene siempre el mismo `article_id` |
| `url`, `title`, `source`, `published_at` | string / ISO 8601 UTC | Datos de la fuente original |
| `body` | string | Texto sin HTML |
| `image_url` | string o `null` (opcional) | Imagen de portada que trae el feed, URL absoluta `https://`; `null` o ausente si el feed no trae imagen. Ver "Imagen de portada" |
| `source_id` | string (opcional) | Id de la fuente en Ingesta (el `id` de `GET /api/sources`). Ver "Fuentes por usuario" |
| `hash` | string | SHA-256 de título + cuerpo; Ingesta solo republica si el hash cambió |

**`article.classified`** — publica Clasificación, consume Búsqueda y Notificaciones.

```json
{
  "event_id": "0e8d2b44-6a1f-4f5e-9c3d-72b1a8d5e620",
  "event_type": "article.classified",
  "occurred_at": "2026-10-25T14:30:02Z",
  "version": 1,
  "payload": {
    "article_id": "5f2a9c1e-8d3b-5c7a-b1e2-0a9d4e6f7c31",
    "url": "https://ejemplo.com/noticia-1",
    "title": "Título de la noticia",
    "summary": "Resumen corto del artículo.",
    "source": "ejemplo.com",
    "source_id": "6ae7aeea22e26d7d67be2610",
    "published_at": "2026-10-25T13:55:00Z",
    "ingested_at": "2026-10-25T14:30:00Z",
    "image_url": "https://ejemplo.com/fotos/noticia-1.jpg",
    "category": "tecnologia",
    "tags": ["inteligencia-artificial", "ecuador"],
    "score": 0.87
  }
}
```

| Campo | Tipo | Notas |
| --- | --- | --- |
| `article_id` | UUID | El mismo de `article.ingested` |
| `url`, `title`, `source`, `published_at` | — | Copiados del evento original |
| `image_url` | string o `null` (opcional) | Copiado tal cual de `article.ingested`; Clasificación no lo usa para clasificar |
| `source_id` | string (opcional) | Copiado tal cual de `article.ingested` |
| `summary` | string | Primeras \~200 palabras o resumen generado |
| `ingested_at` | ISO 8601 UTC | Copia del `occurred_at` de `article.ingested`; necesario para la latencia extremo a extremo |
| `category` | string | Una de las categorías de 5.4 |
| `tags` | string\[\] | Puede ser vacío |
| `score` | número 0–1 | Confianza de la clasificación |

**`user.preferences.updated`** — publica Usuarios, consume Notificaciones.

```json
{
  "event_id": "9c4e7a12-3b5d-4e8f-a6c1-1d2e3f4a5b6c",
  "event_type": "user.preferences.updated",
  "occurred_at": "2026-10-25T14:25:00Z",
  "version": 1,
  "payload": {
    "user_id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
    "categories": ["tecnologia", "deportes"],
    "keywords": ["rabbitmq", "ecuador"],
    "notifications_enabled": true,
    "disabled_sources": ["6ae7aeea22e26d7d67be2611"]
  }
}
```

| Campo | Tipo | Notas |
| --- | --- | --- |
| `user_id` | UUID |  |
| `categories` | string\[\] | Reemplaza por completo la lista anterior (no es un diff) |
| `keywords` | string\[\] | Reemplaza por completo la lista anterior; se comparan contra `tags` y `title` |
| `notifications_enabled` | booleano |  |
| `disabled_sources` | string\[\] (opcional) | `source_id` de las fuentes que el usuario apagó en su feed; reemplaza por completo la lista anterior; ausente equivale a `[]` |

**Imagen de portada (`image_url`)**

Cada noticia puede llevar la URL de su imagen de portada, para mostrarla en el feed, la búsqueda y el detalle.

- **De dónde sale:** Ingesta la toma del propio feed, en este orden: `media:content` de tipo imagen, `media:thumbnail`, `enclosure` de tipo `image/*` y, si no hay ninguno, la primera `<img>` del contenido o resumen. Solo se acepta una URL absoluta `https://`; si no hay, el campo va en `null`.
- **Qué no se hace:** no se descarga ni se guarda la imagen. El frontend la carga directamente desde el medio y, si falla o no hay, muestra un marcador con la categoría.
- **Cómo viaja:** Clasificación la copia sin cambios a `article.classified`; Búsqueda y Notificaciones la guardan y la incluyen en sus respuestas REST y en el mensaje WebSocket (sección 6).
- **Compatibilidad:** es un campo opcional nuevo y los consumidores ignoran los campos que no conocen (regla 4 de la sección 5.5), así que `version` sigue en 1 y ningún servicio deja de funcionar si aún no lo usa.
- **El dataset y el modelo no cambian:** el clasificador usa solo `title + ". " + body`, y `clean_html` ya elimina las etiquetas `<img>` del texto, que queda idéntico con o sin imagen. El dataset que se está recolectando sirve sin cambios.

**Fuentes por usuario (`source_id`, `disabled_sources`)**

Solo el administrador agrega fuentes; cada usuario puede apagar las que no quiere ver en su feed.

- **Activas por defecto:** Usuarios guarda la lista de fuentes **desactivadas** de cada usuario y la publica en `user.preferences.updated`. Una fuente nueva aparece en el feed de todos hasta que cada uno la apague.
- **Cómo viaja:** Ingesta pone el `source_id` en `article.ingested`, Clasificación lo copia a `article.classified` y Búsqueda lo guarda y lo devuelve.
- **Filtro:** Notificaciones no crea alertas de un artículo cuyo `source_id` esté en `disabled_sources` del usuario, ni en vivo ni en el relleno inicial (sección 6). La búsqueda no se filtra.
- **Compatibilidad:** campos opcionales nuevos; `version` sigue en 1 (regla 4 de 5.5).

### 5.4 Categorías válidas

`politica`, `economia`, `tecnologia`, `deportes`, `salud`, `cultura`, `internacional`, `otros`

### 5.5 Reglas para los consumidores

1. **Idempotencia por entidad:** los eventos de artículo se deduplican por `article_id` (upsert); los de preferencias por `user_id`, ignorando un evento con `occurred_at` más antiguo que el ya guardado. Un mensaje repetido se confirma con `ack` y se descarta.
2. **`ack` manual** solo después de procesar y guardar con éxito; nunca `auto-ack`.
3. **Reintentos:** ante un error transitorio, `nack` con `requeue=true`; la cola quorum cuenta las entregas y al pasar de 3 envía el mensaje a su `.dlq`. Un mensaje inválido (JSON roto, campo obligatorio ausente) va directo con `nack` y `requeue=false`.
4. **Campos desconocidos** se ignoran, para poder añadir campos sin romper a nadie.
5. **Cambios incompatibles** (renombrar o quitar campos) suben `version` y se acuerdan por pull request aprobado por los cuatro integrantes.
6. **Prefetch** de 10 mensajes por consumidor, para repartir carga si se escala un servicio a varias réplicas.

## 6. Tiempo real con WebSockets

El WebSocket se usa solo para notificaciones: el artículo nuevo llega al navegador sin recargar en cuanto Notificaciones procesa `article.classified`.

- **Canal:** `ws://localhost:8080/ws/notifications?token=<jwt>`. El gateway valida el token (si no es válido cierra con `1008`) y lo reenvía a `ws://notificaciones:8080/ws?user_id=<id>` con el `user_id` del token; la ruta interna de Notificaciones no cambia. El navegador no puede pedir las alertas de otro usuario.
- **Cuándo se envía:** Notificaciones recibe `article.classified` y lo compara con su copia local de preferencias. Hay coincidencia si la `category` está en `categories` o alguna `keyword` aparece en `tags` o `title`, `notifications_enabled` es verdadero y el `source_id` del artículo no está en `disabled_sources`.
- **Qué guarda:** primero guarda la alerta en su BD y luego la envía a las sesiones abiertas de ese usuario. Así ninguna alerta se pierde si el usuario no está conectado.
- **Relleno inicial (backfill):** Notificaciones guarda también una copia de los `article.classified` de los últimos 7 días. Cuando recibe `user.preferences.updated`, asegura que el usuario tenga alerta de las **20 coincidencias más recientes** (misma regla de coincidencia, sin fuentes desactivadas) y crea solo las que falten, marcadas con `backfill: true`. Así el feed de un usuario nuevo, o de uno que cambia sus intereses, se construye aunque al scrapear no haya noticias nuevas. Es idempotente (alerta única por usuario y artículo) y no se hace si `notifications_enabled` es falso. Esas alertas muestran «Ya publicada» en lugar de la latencia, que solo se mide en las alertas en vivo.
- **Al cambiar las preferencias:** antes del relleno, Notificaciones borra las alertas **no leídas** que ya no coinciden (categoría o keyword quitada, o fuente desactivada). Las leídas se conservan como historial. Desactivar `notifications_enabled` no borra nada: solo deja de crear alertas.
- **Retención:** cada hora Notificaciones borra las alertas y los artículos recientes con más de `ALERTS_RETENTION_DAYS` días (7 por defecto, `NOTIFICACIONES_ALERTS_RETENTION_DAYS` en `.env`), para que no se acumulen. Las noticias antiguas siguen disponibles en Buscar; Búsqueda e Ingesta conservan su historial (Ingesta lo necesita para no republicar).
- **Reflejo en el frontend:** el feed es una bandeja de dos paneles: a la izquierda las pestañas **«Nuevas»** (no leídas) y **«Leídas»**, con una lista que tiene su propio scroll; a la derecha el detalle de la alerta elegida. Cada alerta en vivo entra al inicio de «Nuevas», con su imagen de portada si la tiene, y aumenta el contador de no leídos, sin consulta REST adicional; elegirla la marca como leída. Gracias al relleno inicial el feed no empieza vacío; las noticias más antiguas se consultan en Buscar.
- **Reconexión:** al reconectar, el frontend pide `GET /api/notifications?user_id=<id>&unread=true` y recupera lo que llegó mientras estaba desconectado.

Mensaje enviado al cliente:

```json
{
  "type": "notification.new_article",
  "data": {
    "notification_id": "3d9e1c5a-7b2f-4e61-8a0d-5c4b3a2f1e90",
    "article_id": "5f2a9c1e-8d3b-5c7a-b1e2-0a9d4e6f7c31",
    "title": "Título de la noticia",
    "summary": "Resumen corto del artículo.",
    "category": "tecnologia",
    "tags": ["inteligencia-artificial"],
    "url": "https://ejemplo.com/noticia-1",
    "image_url": "https://ejemplo.com/fotos/noticia-1.jpg",
    "ingested_at": "2026-10-25T14:30:00Z",
    "sent_at": "2026-10-25T14:30:03Z"
  }
}
```

El frontend registra la hora de llegada de cada mensaje; con `ingested_at` y `sent_at` se calcula la latencia de la sección 10.

## 7. API REST por servicio

El frontend accede a todo por el gateway (`http://localhost:8080/api`), que enruta por prefijo al servicio correspondiente. Cada prefijo pertenece a un solo servicio, así no hay rutas en conflicto.

| Prefijo en el gateway | Servicio destino |
| --- | --- |
| `/api/sources` | Ingesta |
| `/api/categories`, `/api/classify`, `/api/model` | Clasificación |
| `/api/search`, `/api/articles` | Búsqueda |
| `/api/users`, `/api/auth` | Usuarios |
| `/api/notifications` | Notificaciones |
| `/ws/notifications` | Notificaciones (WebSocket) |
| `/api/status` | El propio gateway |

| Servicio | Método y ruta | Descripción |
| --- | --- | --- |
| Ingesta | `GET /api/sources` | Lista las fuentes configuradas, con su último estado (cualquier usuario autenticado) |
| Ingesta | `POST /api/sources` | Registra una fuente nueva (RSS o sitio). **Solo administrador** |
| Ingesta | `POST /api/sources/{id}/scrape` | Dispara un scraping manual; responde `202 Accepted` y publica `article.ingested` por cada artículo nuevo. **Solo administrador**. Además, Ingesta revisa sola todas las fuentes activas cada `SCRAPING_INTERVAL_MINUTES` (5 por defecto: los feeds se refrescan cada ~5 minutos) |
| Ingesta | `GET /api/sources/{id}/log` | Últimas 20 ejecuciones de esa fuente (bitácora de scraping) |
| Clasificación | `GET /api/categories` | Lista las categorías válidas |
| Clasificación | `POST /api/classify` | Clasifica un texto de prueba y devuelve categoría, tags y score; no publica eventos |
| Clasificación | `GET /api/model` | Versión del modelo activo y sus métricas (precisión, recall, F1) |
| Búsqueda | `GET /api/search?q=&category=&page=` | Busca artículos por texto y categoría, paginado |
| Búsqueda | `GET /api/articles/{id}` | Detalle de un artículo |
| Usuarios | `POST /api/users` | Registro público: `email`, `password`, `first_names`, `last_names`, `username`. Crea siempre un usuario con rol `usuario`; `409` si el correo o el username ya existen; `422` si un dato no es válido |
| Usuarios | `POST /api/auth/login` | Inicio de sesión con `email` y `password`; devuelve `access_token` (JWT), `token_type: "bearer"`, `expires_in` y los datos del usuario; `401` si las credenciales no son válidas |
| Usuarios | `GET /api/users/me` | Datos, rol y preferencias del usuario del token |
| Usuarios | `GET /api/users/{id}` | Datos y preferencias de un usuario (el propio o, para el administrador, cualquiera) |
| Usuarios | `PUT /api/users/{id}/preferences` | Reemplaza categorías, keywords, `notifications_enabled` y `disabled_sources` del propio usuario; publica `user.preferences.updated` |
| Notificaciones | `GET /api/notifications?user_id=&unread=` | Alertas guardadas del usuario |
| Notificaciones | `PATCH /api/notifications/{id}/read` | Marca una alerta como leída |
| Gateway | `GET /api/status` | Consulta el `/health` de los cinco servicios y devuelve el estado de cada uno |
| Gateway | `GET /api/admin/status` | **Solo administrador.** Panel del sistema: por cada microservicio, su API (código y latencia), su BD (motor, conexión y latencia), su conexión a RabbitMQ, sus colas (mensajes, consumidores y DLQ) y los `details` de su `/health`; además el estado del gateway, de RabbitMQ (versión y colas quorum) y del frontend. Cada grupo queda `ok`, `degraded` (responde pero falla la BD o RabbitMQ, una cola no tiene consumidor o hay mensajes en su DLQ) o `down` (no responde) |

Cada servicio expone también `GET /health`, que revisa su conexión a RabbitMQ y a su BD; Docker lo usa como healthcheck. Si un servicio está caído, el gateway responde `503` solo para su prefijo y el resto sigue funcionando.

Los cinco usan el mismo formato, que lee el panel del administrador; el código es `200` solo si la BD y RabbitMQ están bien (`503` si no):

```json
{"status": "ok", "service": "clasificacion",
 "checks": {"db": {"status": "ok", "engine": "postgresql", "latency_ms": 1},
            "rabbitmq": {"status": "ok"}},
 "details": {"model": "loaded", "model_version": 1, "f1_macro": 0.858}}
```

`details` es libre por servicio: Ingesta (fuentes, fuentes con error, artículos, intervalo de scraping), Clasificación (modelo y métricas), Búsqueda (artículos indexados), Usuarios (usuarios y administradores) y Notificaciones (sesiones WebSocket, alertas y artículos recientes).

### 7.1 Autenticación y permisos

- **Registro:** correo (único, sin distinguir mayúsculas), contraseña (mínimo 8 caracteres; se guarda solo su hash bcrypt), nombres, apellidos y username (único; 3 a 30 caracteres: letras minúsculas, números, `.`, `_` o `-`).
- **Roles:** `admin` y `usuario`. El registro público crea siempre `usuario`. El primer administrador lo crea Usuarios al arrancar con `ADMIN_EMAIL`, `ADMIN_PASSWORD` y `ADMIN_USERNAME` del `.env` (si ya existe, no hace nada).
- **Token:** `POST /api/auth/login` devuelve un JWT HS256 firmado con `JWT_SECRET` (compartido solo entre Usuarios y el gateway), con `sub` = `user_id`, `role` y vencimiento de 8 horas. El frontend lo envía en `Authorization: Bearer <token>` y en el WebSocket como `?token=`.
- **El gateway aplica los permisos** antes de enrutar y reenvía `X-User-Id` y `X-User-Role` al servicio (los servicios no son accesibles desde fuera de la red de Docker):

| Ruta | Sin token | `usuario` | `admin` |
| --- | --- | --- | --- |
| `POST /api/users`, `POST /api/auth/login`, `GET /api/categories`, `GET /api/status` | sí | sí | sí |
| `GET /api/sources`, `/api/search`, `/api/articles`, `/api/classify`, `/api/model` | `401` | sí | sí |
| `POST /api/sources`, `POST /api/sources/{id}/scrape`, `GET /api/admin/status` | `401` | `403` | sí |
| `/api/users/me`, `/api/users/{id}` y `/api/users/{id}/preferences` | `401` | solo el propio `{id}` (`403` si no) | sí (`GET`) |
| `GET /api/notifications?user_id=` | `401` | solo el propio `user_id` (`403` si no) | solo el propio |
| `PATCH /api/notifications/{id}/read` | `401` | solo alertas propias (Notificaciones compara con `X-User-Id`; `404` si no es suya) | solo propias |
| `/ws/notifications?token=` | cierre `1008` | sí | sí |

- **Token vencido o inválido:** `401` (`1008` en el WebSocket); el frontend vuelve a la pantalla de inicio de sesión.

## 8. Docker y despliegue

Todo arranca con `docker compose up -d --build`: 9 contenedores en la red `newsproject-net`. Cada microservicio de negocio es **un solo contenedor con su backend y su base de datos dentro**. Solo el gateway, el frontend y el panel de RabbitMQ publican puertos al equipo anfitrión.

| Contenedor | Contiene | Imagen base | Puerto al anfitrión | Depende de |
| --- | --- | --- | --- | --- |
| `rabbitmq` | Broker | `rabbitmq:3.13-management` | 15672 (panel); 5672 solo en desarrollo | — |
| `rabbitmq-init` | Carga `definitions.json`, crea el usuario de monitoreo y termina | `curlimages/curl` | — | `rabbitmq` (healthy) |
| `ingesta` | FastAPI + MongoDB | `mongo:7` + Python | — | `rabbitmq-init` (completado) |
| `clasificacion` | FastAPI + PostgreSQL | `postgres:16` + Python | — | `rabbitmq-init` (completado) |
| `busqueda` | FastAPI + MongoDB | `mongo:7` + Python | — | `rabbitmq-init` (completado) |
| `usuarios` | FastAPI + PostgreSQL | `postgres:16` + Python | — | `rabbitmq-init` (completado) |
| `notificaciones` | Spring Boot + PostgreSQL | `postgres:16` + JRE 21 copiado de `eclipse-temurin:21-jre` | — | `rabbitmq-init` (completado) |
| `gateway` | FastAPI, sin BD | `python:3.12-slim` | 8080 | los cinco servicios (iniciados) |
| `frontend` | Build de React servido con Nginx | `node:20` (build) + `nginx` | 3000 | `gateway` |

Cada contenedor de servicio ejecuta dos procesos con `supervisord`: la base de datos, que escucha solo en `localhost` dentro del contenedor, y el backend. Patrón para Clasificación; los demás servicios cambian la imagen base, el comando de la BD y el del backend.

`clasificacion/Dockerfile`

```dockerfile
FROM postgres:16
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv supervisor \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
COPY . .
COPY supervisord.conf /etc/supervisor/conf.d/app.conf
EXPOSE 8000
ENTRYPOINT []
CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
```

`clasificacion/supervisord.conf`

```ini
[program:db]
command=docker-entrypoint.sh postgres -c listen_addresses=localhost
priority=10
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
redirect_stderr=true

[program:api]
command=/opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
directory=/app
priority=20
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
redirect_stderr=true
```

En MongoDB el programa `db` es `docker-entrypoint.sh mongod --bind_ip 127.0.0.1`; en Notificaciones el programa `api` es `java -jar /app/notificaciones.jar`.

Fragmento de `docker-compose.yml`:

```yaml
  clasificacion:
    build: ./clasificacion
    container_name: newsproject-clasificacion
    restart: unless-stopped
    environment:
      POSTGRES_DB: clasificacion
      POSTGRES_USER: ${CLASIFICACION_DB_USER}
      POSTGRES_PASSWORD: ${CLASIFICACION_DB_PASS}
      DATABASE_URL: postgresql://${CLASIFICACION_DB_USER}:${CLASIFICACION_DB_PASS}@localhost:5432/clasificacion
      RABBITMQ_URL: amqp://${RABBITMQ_USER}:${RABBITMQ_PASS}@rabbitmq:5672
    volumes: ["clasificacion_data:/var/lib/postgresql/data"]
    depends_on:
      rabbitmq-init: { condition: service_completed_successfully }
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 10s
      retries: 10
      start_period: 30s
    networks: [newsproject-net]
```

- **Datos persistentes:** cada BD guarda sus datos en un volumen con nombre (`ingesta_data`, `clasificacion_data`, etc.), así reconstruir el contenedor no borra la información.
- **Aislamiento:** la BD escucha solo en `localhost`, por lo que ningún otro contenedor puede conectarse a ella; la regla "ningún servicio lee la BD de otro" queda garantizada por la red.
- **Arranque:** `supervisord` inicia la BD y el backend sin esperar uno al otro, así que el backend reintenta la conexión a su BD y a RabbitMQ con espera creciente. `/health` responde 200 solo cuando ambas conexiones están activas.
- **Credenciales:** cada servicio tiene su usuario y clave de BD en `.env` (`INGESTA_DB_USER`, `CLASIFICACION_DB_USER`, etc.); además `JWT_SECRET` (solo Usuarios y gateway) y los datos del primer administrador (`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_USERNAME`, solo Usuarios). Para el panel del administrador, `rabbitmq-init` crea un usuario de RabbitMQ de **solo monitoreo** (`RABBITMQ_MONITOR_USER`/`RABBITMQ_MONITOR_PASS`, etiqueta `monitoring`, sin permisos para configurar, leer ni publicar) que usa el gateway para consultar las colas; así el gateway no tiene la clave de administrador del broker. `.env.example` lleva valores de ejemplo y `.env` nunca se sube.
- **Inspeccionar una BD:** `docker exec -it newsproject-clasificacion psql -U <usuario> clasificacion` (o `mongosh` en Ingesta y Búsqueda); no hace falta exponer puertos de BD.
- **Topología:** al cambiar las colas a quorum hay que recrear el volumen de RabbitMQ (`docker compose down -v`), porque una cola existente no cambia de tipo.

* **Tolerancia al arrancar:** el gateway depende de los servicios con `service_started`, no `service_healthy`: si uno falla, el gateway arranca igual y responde `503` solo en sus rutas. Nginx del frontend resuelve `gateway` en cada petición (DNS interno de Docker), así que arranca aunque el gateway esté detenido y devuelve `503` en JSON si no responde.
* **Base verificada:** el 25/10/2026, `docker compose up -d --build` en `main` levantó los 9 contenedores, con los servicios `healthy`, `rabbitmq-init` en `Exited (0)` y las 8 colas de tipo quorum. El 01/11/2026 la verificación final del sistema completo (registro y roles, eventos, demo desde la app con Playwright y tolerancia a fallos) pasó 134 de 134 pruebas; los scripts están en `verificacion/scripts/`. Para correrlo hace falta `cp .env.example .env` (con `JWT_SECRET`, `ADMIN_*` y `RABBITMQ_MONITOR_*`) y, en Linux, que el usuario esté en el grupo `docker`.

### 8.1 Modo distribuido en 4 PCs (opcional)

Todo lo anterior describe el modo de una PC, que sigue siendo el principal. Como alternativa, el mismo sistema se puede repartir en 4 PCs Linux, por switch (LAN) o por Tailscale, con `docker-compose.distribuido.yml` (proyecto `newsproject-dist`) y `deploy/levantar.sh <switch|tailscale>`. No cambia el contrato de eventos ni las APIs: solo dónde corre cada contenedor y cómo se encuentran.

| PC | Perfiles | Puertos publicados en su IP |
| --- | --- | --- |
| pc1 | `entrada` (gateway + frontend), `usuarios` | 8080, 3000, 8004 |
| pc2 | `ingesta` | 8001 |
| pc3 | `clasificacion`, `busqueda` | 8002, 8003 |
| pc4 | `broker` (RabbitMQ + `rabbitmq-init`), `notificaciones` | 5672, 15672, 8005 |

Diferencias con el modo de una PC:

- **Direcciones:** los servicios llegan a RabbitMQ por la IP de pc4 y el gateway llega a cada servicio por la IP de su PC; Nginx sigue hablando con el gateway por el DNS de Docker porque están en la misma PC. Las IPs vienen de `.env.switch` o `.env.tailscale`, y cada puerto se publica solo en la IP de su PC.
- **Arranque:** no hay `depends_on` entre PCs. Cada servicio reintenta toda su preparación de RabbitMQ (conexión, exchange, cola y consumidor) hasta que pc4 y `rabbitmq-init` están listos.
- **Token interno:** como los servicios quedan publicados en la red, el gateway envía `X-Internal-Token` (variable `INTERNAL_TOKEN`, que toma el valor de `DISTRIBUTED_INTERNAL_TOKEN`) en REST, `/health` y el WebSocket, y cada servicio responde `403` si no coincide; `GET /health` queda libre. En el modo de una PC la variable está vacía y no cambia nada.
- **Datos:** cada PC guarda solo las bases de datos de sus servicios, en volúmenes `newsproject-dist_*`, separados de los del modo de una PC.
- **Verificación:** `deploy/revisar_red.sh <switch|tailscale>` revisa el alcance de cada PC, el puerto de cada componente y su `/health`; los scripts de `verificacion/scripts/` aceptan `NP_GATEWAY`, `NP_AMQP_URL` y otras variables para apuntar al modo distribuido.

Pasos completos, orden de pruebas y problemas comunes: [`docs/despliegue-distribuido.md`](despliegue-distribuido.md).

## 9. Estructura del repositorio y flujo Git

Un solo repositorio ([YooneR1209/newsproject](https://github.com/YooneR1209/newsproject)) con una carpeta por servicio y la infraestructura compartida en `infra/`.

```
newsproject/
├── docker-compose.yml
├── docker-compose.override.yml   (puerto 5672 en desarrollo)
├── .env.example
├── .gitignore                    (.env, .idea/, dataset.csv, __pycache__/, node_modules/, target/, verificacion/ejecuciones)
├── README.md
├── .github/
│   └── workflows/dataset.yml     (recolecta el dataset cada hora)
├── docs/
│   ├── arquitectura.md           (este documento)
│   ├── eventos.md                (contrato de eventos, sección 5)
│   ├── img/arquitectura.png      (diagrama; fuente editable arquitectura.svg y genera_arquitectura.py)
│   ├── capturas/                 (pantallas de la app para el README)
│   └── declaratoria-ia.pdf
├── infra/
│   └── rabbitmq/definitions.json
├── ingesta/          (Dockerfile + supervisord.conf: backend y MongoDB)
├── clasificacion/    (Dockerfile + supervisord.conf: backend y PostgreSQL)
│   ├── data/feeds.csv            (feeds por sección para el dataset)
│   └── tools/collect_dataset.py  (recolector; train.py y model.joblib van aquí también)
├── busqueda/         (Dockerfile + supervisord.conf: backend y MongoDB)
├── usuarios/         (Dockerfile + supervisord.conf: backend y PostgreSQL)
├── notificaciones/   (Dockerfile + supervisord.conf: backend y PostgreSQL)
├── gateway/          (Dockerfile)
├── frontend/         (Dockerfile + nginx.conf; páginas en src/pages/)
└── verificacion/
    ├── scripts/                  (pruebas: API, eventos, Playwright, tolerancia a fallos)
    └── ejecuciones/<fecha_hora>/ (informe, logs y capturas de cada ejecución; no se versiona)

Rama dataset: solo dataset.csv, actualizado por GitHub Actions.
```

`infra/postgres/init.sql` deja de ser necesario: cada contenedor de servicio con PostgreSQL crea su propia base con `POSTGRES_DB`.

**Flujo de ramas**

1. Cada integrante desarrolla su servicio en su rama: `kevin-dev`, `fabricio-dev`, `ariana-dev`, `ariel-dev`.
2. Los cambios llegan a `main` por pull request revisado por otro integrante.
3. Los contratos de eventos (sección 5) y de REST (sección 7) solo cambian por pull request aprobado por los cuatro.
4. Antes de cada merge, `docker compose up -d --build` debe levantar el sistema completo.
5. Al terminar se publica un único release `v1.0` desde `main`; no hay releases intermedios.

| Entregable | Ubicación |
| --- | --- |
| Documento de Arquitectura | `docs/arquitectura.md` |
| Contrato de eventos | `docs/eventos.md` |
| Código con rama por integrante, Dockerfiles y compose | Repositorio Git |
| README con `docker compose up` | Raíz del repositorio |
| Declaratoria de IA firmada | `docs/declaratoria-ia.pdf` |
| Release v1.0 | Pestaña Releases del repositorio |

## 10. Métricas y trazabilidad

Las marcas de tiempo que viajan en los eventos permiten medir, sin herramientas externas, las métricas que pide el informe.

| Métrica | Cómo se calcula | Dónde se registra |
| --- | --- | --- |
| Latencia extremo a extremo (ms) | llegada al frontend − `ingested_at` | Frontend, por cada mensaje WebSocket |
| Latencia por etapa (ms) | `occurred_at` de `article.classified` − `ingested_at` (clasificación); `sent_at` − `occurred_at` de `article.classified` (notificación) | Logs de cada servicio |
| Throughput (art/s) | artículos indexados por Búsqueda ÷ duración de la prueba | Búsqueda |
| Calidad de clasificación | precisión, recall y F1 macro y por categoría sobre el conjunto de prueba revisado a mano (sección 3.2) | `GET /api/model` |
| Disponibilidad bajo fallos (%) | eventos procesados ÷ eventos publicados, con un servicio detenido y luego reiniciado | Panel del sistema (`/admin`), panel de RabbitMQ y conteos en cada BD |
| Tiempo de recuperación (s) | desde que el servicio reinicia hasta que su cola queda en 0 mensajes y su tarjeta vuelve a verde | Panel del sistema (`/admin`, se refresca cada 10 s) y panel de RabbitMQ |

Cada servicio escribe logs en JSON con `event_id`, `article_id`, la etapa y la marca de tiempo, para poder seguir un artículo de punta a punta.

## 11. Escenario de demo y pruebas de tolerancia a fallos

La demo recorre el flujo completo pedido en el trabajo práctico (frontend → API → cola → microservicio → actualización en pantalla) y termina con tres caídas controladas.

**Guion del flujo normal**

1. Con `docker compose up -d --build` corriendo, un usuario se registra en el frontend (correo, contraseña, nombres, apellidos y username), inicia sesión y elige la categoría `tecnologia`; en Fuentes apaga una fuente que no le interesa.
2. En el panel de RabbitMQ (puerto 15672) se ve llegar `user.preferences.updated` a Notificaciones.
3. En otra ventana, el administrador inicia sesión, agrega una fuente nueva y dispara su scraping (`POST /api/sources` y `POST /api/sources/{id}/scrape`); el usuario normal no ve esos botones y el gateway le respondería `403`.
4. En el panel de RabbitMQ se ve pasar `article.ingested` y luego `article.classified` hacia las dos colas; en el panel del sistema (`/admin`) todas las tarjetas siguen en verde.
5. El artículo aparece arriba de «Nuevas» en el feed del usuario por WebSocket, sin recargar, con su latencia, y sube el contador de no leídos.
6. El usuario lo busca en Buscar (`GET /api/search?q=`) y lo encuentra indexado.

Antes de la demo conviene `docker compose down -v && docker compose up -d --build`: deja las DLQ vacías (el panel en verde) y sin usuarios ni fuentes de prueba.

**Pruebas de tolerancia a fallos**

| Prueba | Qué se hace | Resultado esperado |
| --- | --- | --- |
| Búsqueda caída | `docker compose stop busqueda`, se repite el scraping, luego `start` | En `/admin` la tarjeta de Búsqueda pasa a rojo. Los mensajes esperan en `busqueda.article-classified`; al reiniciar se consumen y los artículos quedan indexados. Las alertas siguen llegando mientras tanto |
| Usuarios caído | `docker compose stop usuarios` y se dispara un scraping | Notificaciones sigue enviando alertas con su copia local de preferencias; solo falla `/api/users` (503) |
| Mensaje envenenado | Se publica desde el panel de RabbitMQ un `article.ingested` sin `title` | Clasificación lo rechaza; el mensaje termina en `clasificacion.article-ingested.dlq` (en `/admin`, Clasificación en amarillo con «1 mensaje fallido») y la cola principal sigue fluyendo |
| Duplicado | Se scrapea dos veces la misma fuente | Mismo `article_id`: ni Búsqueda ni Notificaciones duplican artículos o alertas |

Estas pruebas alimentan el objetivo específico 2 del informe y la métrica de disponibilidad de la sección 10.

## 12. Decisiones y riesgos

| Decisión o riesgo | Tratamiento |
| --- | --- |
| RabbitMQ en lugar de Kafka | Cumple el requisito del curso y es más simple de operar con Docker |
| Un exchange `topic` con una cola por consumidor y evento | Permite agregar consumidores sin tocar a los productores |
| Usuarios separado de Notificaciones | Una responsabilidad por servicio; Notificaciones no depende de Usuarios en tiempo de ejecución |
| Backend y BD de cada servicio en un mismo contenedor | El servicio y sus datos se levantan, detienen y reinician como una unidad, y la BD no es accesible desde fuera. A cambio, cada contenedor corre dos procesos (supervisord) y el servicio no puede escalar a varias réplicas, porque cada réplica tendría su propia BD |
| Colas quorum con `x-delivery-limit: 3` | RabbitMQ cuenta los reintentos y envía a la DLQ sin lógica extra en cada consumidor |
| `article_id` como UUID v5 de la URL | El mismo artículo tiene siempre el mismo id, lo que hace idempotentes a todos los consumidores |
| Clasificador TF-IDF + Naive Bayes o regresión logística | Rápido, explicable y medible con precisión, recall y F1; depende de tener un dataset etiquetado |
| Dataset etiquetado por la sección del feed, recolectado por GitHub Actions | Sin etiquetado manual y sin depender de que una PC esté encendida. A cambio hay ruido en las etiquetas y algunas categorías dependen de una sola fuente; se compensa con un conjunto de prueba mixto (Ecuador y otros países) revisado a mano |
| Ingesta y el recolector arman el texto con las mismas funciones | El modelo ve en producción textos iguales a los de entrenamiento; el costo es mantener esas funciones sincronizadas en dos lugares |
| Un servicio no encuentra el broker al arrancar | Espera a `rabbitmq-init` y reintenta con espera creciente |
| Un servicio falla al arrancar | El gateway depende de él solo como "iniciado" y responde `503` en sus rutas; el resto del sistema sigue funcionando |
| Fuentes de scraping que bloquean o cambian de formato | Preferir feeds RSS; registrar el error en la bitácora y seguir con las demás fuentes. Ya pasó: El Comercio responde 403 a GitHub y se quitó del dataset |
| Pocas noticias etiquetadas en alguna categoría | Medir F1 por categoría; si es bajo, agregar fuentes, usar `class_weight="balanced"` o fusionar la categoría con `otros` |
| Contratos que cambian a mitad del proyecto | Campo `version` en cada evento y cambios solo por pull request aprobado por los cuatro |
| Autenticación con JWT validado en el gateway | Un solo punto aplica los permisos y los servicios siguen sin estado de sesión; el secreto se comparte solo entre Usuarios y el gateway. A cambio, un token no se puede revocar antes de vencer (8 horas) y no hay recuperación de contraseña |
| Fuentes por usuario como lista de desactivadas | Las fuentes nuevas llegan a todos sin que nadie tenga que activarlas; el filtro lo aplica Notificaciones con su copia local, sin llamar a Usuarios ni a Ingesta |

## 13. Cambios respecto a la versión anterior y pendientes

| Tema | Versión 21/10 | Esta versión | Origen |
| --- | --- | --- | --- |
| Microservicios | 4 (Notificaciones gestionaba usuarios) | 5 (Usuarios aparte) | Repositorio |
| Exchange y eventos | `news.events`; `article.raw`, `article.classified` | `newsproject.events`; `article.ingested`, `article.classified`, `user.preferences.updated` | Repositorio |
| Formato de mensaje | camelCase, `data` | snake\_case, `payload`, `version`, `ingested_at`, `score` | Repositorio |
| Imagen de portada | No incluida | Campo opcional `image_url` tomado del feed, copiado por Clasificación y mostrado en el frontend; no cambia el dataset ni `version` | Decisión del grupo |
| Nombres de colas | `q.classification`, `q.search`, `q.notifications` | `<servicio>.<evento>` + `.dlq` | Repositorio |
| Reintentos y DLQ | DLQ sin mecanismo definido | Colas quorum con límite de 3 entregas + DLX | Corrección |
| Idempotencia | `articleId` sin regla de generación | `article_id` = UUID v5 de la URL; dedup por entidad | Corrección |
| Bases de datos | Un contenedor de BD aparte por servicio, motores distintos | Backend y BD en el mismo contenedor por servicio, con credenciales propias; motores del repositorio | Repositorio + decisión del grupo |
| Stack | Búsqueda en NestJS; Notificaciones y gateway en Express | Python/FastAPI; Notificaciones en Java 21 / Spring Boot | Repositorio |
| Clasificación | Reglas de palabras clave | TF-IDF + Naive Bayes o regresión logística entrenado con noticias etiquetadas | Decisión del grupo |
| Dataset | No definido | Feeds por sección, recolector en `clasificacion/tools/`, GitHub Actions cada hora y rama `dataset` | Decisión del grupo |
| API REST | 11 rutas | 18 rutas: se suman `GET /api/sources/{id}/log`, `POST /api/auth/login`, `GET /api/users/me`, `GET /api/status`, `GET /api/admin/status` y las de Clasificación y Notificaciones; sale `GET /api/users?email=` (entrar sin contraseña) | Guías de desarrollo + decisión del grupo |
| Arranque del gateway | Espera a todos los servicios | Espera solo a que inicien; `503` por servicio caído | Prueba de la base |
| Usuarios y permisos | Sin contraseña; se entraba con el email | Registro con contraseña, login con JWT, roles `admin` / `usuario`; solo el admin agrega fuentes y cada usuario apaga fuentes en su feed (`source_id`, `disabled_sources`) | Decisión del grupo |
| Carpetas | `ingesta-service/`, `api-gateway/`… | `ingesta/`, `gateway/`… | Repositorio |
| Feed | Lista de alertas en vivo | Bandeja en dos paneles (Nuevas · Leídas + detalle); relleno inicial con las 20 coincidencias recientes (`backfill`); al cambiar preferencias se borran las no leídas que ya no coinciden; retención de 7 días | Decisión del grupo |
| Ingesta automática | Cada 10 minutos | Cada 5 minutos (`SCRAPING_INTERVAL_MINUTES`), al ritmo en que los medios refrescan sus feeds | Decisión del grupo |
| Monitoreo | Panel de RabbitMQ | Además, panel del sistema `/admin` (solo admin) con el estado de cada servicio, su BD y sus colas; `/health` con formato común | Decisión del grupo |

**Pendientes para alinear el repositorio con este documento**

- [x] `definitions.json`: colas principales a tipo quorum con `x-delivery-limit: 3`
- [x] `docker-compose.yml`: BD dentro del contenedor de cada servicio, credenciales por servicio en `.env.example` y el puerto 5672 en `docker-compose.override.yml`
- [x] `docker-compose.yml` y `nginx.conf`: gateway y frontend toleran servicios caídos al arrancar
- [x] `docs/eventos.md`: `article_id` como UUID v5 e idempotencia por entidad
- [x] README corregido y `.idea/` fuera del repositorio
- [x] Base probada con `docker compose up -d --build`: 9 contenedores, servicios healthy, 8 colas quorum
- [x] Fuente del dataset: feeds por sección, recolector y GitHub Actions con la rama `dataset`
- [ ] Dejar correr la recolección unos 5 días, generar `test_set.csv` y revisarlo a mano
- [x] Entrenar el modelo final (`clasificacion/model/`, regresión logística, F1 macro 0,858)
- [ ] Revisar `MIN_SCORE` (hoy 0,5) con el conjunto de prueba: con feeds generales muchas noticias caen en `otros`
- [x] Implementar cada servicio sobre su plantilla (`/health` real, consumidores, endpoints)
- [x] Sincronizar `docs/arquitectura.md` y docs/eventos.md (campo image\_url) del repositorio con esta versión
- [x] Implementar usuarios con contraseña, roles y fuentes por usuario (secciones 5.3 y 7.1): Usuarios, gateway, Ingesta, Clasificación, Búsqueda, Notificaciones y frontend
- [x] Feed en dos paneles, relleno inicial, limpieza por preferencias y retención; panel del sistema `/admin`
- [x] Diagrama de arquitectura actualizado y detallado (sección 2)
- [ ] Aprobar por pull request, entre los cuatro, los cambios de contrato de esta versión (secciones 5.3, 6, 7 y 7.1; `docs/eventos.md` 3.1–3.5 y 7)
- [ ] Quitar de `clasificacion/data/feeds.csv` los feeds de Ecuavisa (responden 403 a clientes que no son navegador)
- [ ] Informe: actualizar herramientas (Notificaciones en Java) y reemplazar la metodología de Raft/Paxos que quedó de la plantilla
