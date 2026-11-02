# Despliegue distribuido en 4 PCs

Guía para levantar newsproject repartido en **4 PCs Linux** conectadas por un **switch (LAN)** o por **Tailscale**. Es un modo **opcional**: el modo de una sola PC (`docker compose up -d --build`, ver [`README.md`](../README.md)) sigue igual y no se ve afectado.

Los microservicios, los eventos y el contrato ([`docs/eventos.md`](eventos.md)) son exactamente los mismos; solo cambia **dónde** corre cada contenedor y **cómo** se encuentran entre ellos.

## Índice

1. [Diferencia con el modo de una PC](#1-diferencia-con-el-modo-de-una-pc)
2. [Reparto de PCs y puertos](#2-reparto-de-pcs-y-puertos)
3. [Requisitos](#3-requisitos)
4. [Archivos de configuración](#4-archivos-de-configuración)
5. [Paso a paso con switch (LAN)](#5-paso-a-paso-con-switch-lan)
6. [Paso a paso con Tailscale](#6-paso-a-paso-con-tailscale)
7. [Arranque](#7-arranque)
8. [Orden de pruebas](#8-orden-de-pruebas)
9. [Comandos del día a día](#9-comandos-del-día-a-día)
10. [Problemas comunes](#10-problemas-comunes)
11. [Seguridad: token interno](#11-seguridad-token-interno)

---

## 1. Diferencia con el modo de una PC

| | Modo de una PC | Modo distribuido |
|---|---|---|
| Archivo de Compose | `docker-compose.yml` (+ `docker-compose.override.yml`) | `docker-compose.distribuido.yml` |
| Proyecto de Docker | `newsproject` | `newsproject-dist` (contenedores `newsproject-dist-*`, volúmenes propios) |
| Cómo se levanta | `docker compose up -d --build` | `deploy/levantar.sh <switch\|tailscale>` en cada PC |
| Variables | `.env` | `.env.distribuido` + `.env.switch` o `.env.tailscale` + `.env.pc` |
| Cómo se encuentran los servicios | Nombres de Docker (`rabbitmq`, `ingesta`…) en una red interna | IP de cada PC y puertos publicados (`PC4_IP:5672`, `PC2_IP:8001`…) |
| Puertos de los servicios | No se publican (solo gateway, frontend y panel de RabbitMQ) | Se publican **solo en la IP de esa PC** (`MI_IP`) |
| Protección de los servicios | La red interna de Docker: nadie de fuera llega a ellos | **Token interno**: sin `X-Internal-Token` responden `403` (sección 11) |
| Orden de arranque | `depends_on` lo garantiza | No hay `depends_on` entre PCs: cada servicio reintenta solo hasta que RabbitMQ y sus colas existen |
| Dirección de la app | `http://localhost:3000` | `http://<PC1_IP>:3000` desde cualquier equipo de la red |

Ambos modos pueden convivir en el repositorio y en la misma PC, pero **no al mismo tiempo** si usan los mismos puertos: antes de levantar uno, detén el otro (`docker compose stop` o `deploy/levantar.sh <red> stop`).

## 2. Reparto de PCs y puertos

```
Navegador ─► pc1:3000 frontend (Nginx) ─► pc1 gateway ─┬─► pc1:8004 usuarios
                                                      ├─► pc2:8001 ingesta
                                                      ├─► pc3:8002 clasificacion
                                                      ├─► pc3:8003 busqueda
                                                      └─► pc4:8005 notificaciones (REST y WebSocket)

Eventos: ingesta, clasificacion, busqueda, usuarios y notificaciones ─► pc4:5672 RabbitMQ
```

| PC | Perfiles | Contenedores | Puertos publicados en su IP |
|---|---|---|---|
| **pc1** | `entrada`, `usuarios` | gateway, frontend, usuarios | 8080 (gateway), 3000 (frontend), 8004 (usuarios) |
| **pc2** | `ingesta` | ingesta | 8001 |
| **pc3** | `clasificacion`, `busqueda` | clasificacion, busqueda | 8002, 8003 |
| **pc4** | `broker`, `notificaciones` | rabbitmq, rabbitmq-init, notificaciones | 5672 (AMQP), 15672 (panel), 8005 (notificaciones) |

Dentro de cada contenedor los puertos no cambian (8000 en los servicios Python, 8080 en Notificaciones); `levantar.sh` solo los publica hacia fuera con el número de la tabla.

**Quién habla con quién:**

| Origen | Destino | Para qué |
|---|---|---|
| Navegador (cualquier equipo de la red) | pc1:3000 | La aplicación. Nginx reenvía `/api` y `/ws` al gateway de la misma PC |
| pc1 (gateway) | pc2:8001, pc3:8002, pc3:8003, pc1:8004, pc4:8005 | REST y WebSocket hacia los servicios, con `X-Internal-Token` |
| pc1 (gateway) | pc4:15672 | Panel del administrador (colas y estado del broker) |
| pc1, pc2, pc3 y pc4 (servicios) | pc4:5672 | Publicar y consumir eventos |

La base de datos de cada servicio sigue **dentro de su contenedor** y no se publica: cada PC guarda solo los datos de sus servicios.

## 3. Requisitos

En **las 4 PCs**:

- Linux con Docker y **Docker Compose v2.20 o superior** (`docker compose version`). Tu usuario en el grupo `docker`.
- El repositorio clonado **en la misma rama y el mismo commit** (`git log -1 --oneline` debe dar lo mismo en las 4).
- Reloj sincronizado: `timedatectl` debe decir `System clock synchronized: yes`. Si los relojes no coinciden, las latencias del feed salen mal (incluso negativas).
- `curl`, `ping` y `python3` (los usa `deploy/revisar_red.sh`; suelen venir instalados).
- **Internet en pc2** para que Ingesta lea los feeds RSS, y **en todas** para construir las imágenes la primera vez (descargan imágenes base y paquetes). Si el switch no tiene salida a internet, construye antes conectado a internet o deja a cada PC con una segunda conexión (Wi-Fi) para internet.

Además, según la red:

- **Switch:** una IP **fija** por PC en la misma subred (por defecto `192.168.50.11` a `.14`).
- **Tailscale:** las 4 PCs en la **misma tailnet** (misma cuenta u organización de Tailscale).

## 4. Archivos de configuración

Todos van en la raíz del repositorio. Los `.example` están versionados; **las copias sin `.example` no se suben** (están en `.gitignore`).

| Archivo | Contenido | ¿Igual en las 4 PCs? |
|---|---|---|
| `.env.distribuido` | Claves: RabbitMQ, bases de datos, `JWT_SECRET`, administrador inicial, usuario de monitoreo y `DISTRIBUTED_INTERNAL_TOKEN` | **Sí, idéntico** |
| `.env.switch` | `PC1_IP` … `PC4_IP` en la LAN | **Sí, idéntico** |
| `.env.tailscale` | `PC1_IP` … `PC4_IP` de Tailscale (`100.x.y.z`) | **Sí, idéntico** |
| `.env.pc` | `PC=pc1`, `pc2`, `pc3` o `pc4`: qué PC es esta | **No: uno distinto en cada PC** |

`deploy/levantar.sh` lee estos archivos, calcula los perfiles y la IP de la PC (`MI_IP`) y ejecuta `docker compose`. No hace falta escribir `MI_IP` en ningún lado.

### Crear `.env.distribuido` (una sola vez, en una PC)

```bash
cp .env.distribuido.example .env.distribuido
```

Edítalo y reemplaza **todos** los `cambiar_...`. Para los secretos largos (`JWT_SECRET` y `DISTRIBUTED_INTERNAL_TOKEN`, que deben ser distintos entre sí):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Después **copia ese mismo archivo** a las otras 3 PCs (USB, `scp`, etc.). Por ejemplo, desde pc1:

```bash
scp .env.distribuido usuario@<PC2_IP>:~/newsproject/.env.distribuido
```

> No lo mandes por el chat del grupo ni lo subas al repositorio: tiene todas las claves.

## 5. Paso a paso con switch (LAN)

### 5.1 Conectar y fijar las IPs

1. Conecta las 4 PCs al switch con cable.
2. En **cada PC**, mira el nombre de la conexión cableada:

   ```bash
   nmcli -t -f NAME,DEVICE connection show --active
   ```

3. Fija su IP (ejemplo para pc1; en pc2 usa `.12`, en pc3 `.13`, en pc4 `.14`). Cambia `"Conexión cableada 1"` por el nombre que viste:

   ```bash
   sudo nmcli connection modify "Conexión cableada 1" ipv4.method manual ipv4.addresses 192.168.50.11/24
   sudo nmcli connection up "Conexión cableada 1"
   ip -4 addr        # debe aparecer 192.168.50.11
   ```

   Si el switch está conectado a un router con DHCP, puedes usar las IPs que asigne el router; en ese caso reserva una IP fija por PC en el router y usa esas en `.env.switch`.

4. Desde cualquier PC, comprueba que llegas a las otras: `ping -c 2 192.168.50.12`.

### 5.2 Archivos

En **cada PC**, dentro del repositorio:

```bash
cp .env.switch.example .env.switch     # cambia las IPs solo si no usas 192.168.50.11-.14
cp .env.pc.example .env.pc             # edita: PC=pc1 (o pc2, pc3, pc4 según la PC)
# y copia aquí el .env.distribuido común (sección 4)
```

`.env.switch` debe ser **igual en las 4 PCs**.

### 5.3 Revisar la red y levantar

Sigue con la [sección 7](#7-arranque) usando `switch`:

```bash
deploy/revisar_red.sh switch
deploy/levantar.sh switch
```

## 6. Paso a paso con Tailscale

Útil cuando las PCs no están en el mismo lugar o no hay switch. El tráfico va cifrado por Tailscale.

### 6.1 Instalar y unir las PCs

En **cada PC**:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # abre el enlace que muestra e inicia sesión con la cuenta del grupo
tailscale ip -4              # anota esta IP 100.x.y.z
```

Las 4 PCs deben iniciar sesión en la **misma tailnet**. Comprueba desde una PC que llegas a otra: `tailscale ping <IP 100.x de otra PC>`.

### 6.2 Archivos

En **cada PC**, dentro del repositorio:

```bash
cp .env.tailscale.example .env.tailscale
cp .env.pc.example .env.pc             # edita: PC=pc1 (o pc2, pc3, pc4)
# y copia aquí el .env.distribuido común (sección 4)
```

Edita `.env.tailscale` con las 4 IPs que anotaste (`PC1_IP=100.…` de la PC que hará de pc1, etc.) y copia **el mismo** archivo a las 4 PCs.

### 6.3 Revisar la red y levantar

Sigue con la [sección 7](#7-arranque) usando `tailscale`:

```bash
deploy/revisar_red.sh tailscale
deploy/levantar.sh tailscale
```

> Tailscale debe estar conectado (`tailscale status`) **antes** de levantar: Docker publica los puertos en la IP `100.x`, y si todavía no existe, el contenedor no arranca.

## 7. Arranque

Usa `switch` o `tailscale` según tu red. En los ejemplos, `<red>`.

1. **En cada PC**, comprueba la configuración sin levantar nada:

   ```bash
   deploy/levantar.sh <red> config --services
   ```

   Debe listar los servicios de esa PC (por ejemplo, en pc4: `rabbitmq`, `rabbitmq-init`, `notificaciones`). Si aparece `AVISO: esta PC no tiene la IP ...`, el `.env.pc` o la IP están mal (ver [problemas comunes](#10-problemas-comunes)).

2. **Levanta en este orden** (recomendado; si no se respeta, los servicios igual se recuperan solos, pero tardan más):

   | Orden | PC | Comando | Espera a que… |
   |---|---|---|---|
   | 1 | pc4 | `deploy/levantar.sh <red>` | `deploy/levantar.sh <red> ps -a` muestre `rabbitmq` **healthy** y `rabbitmq-init` **Exited (0)** |
   | 2 | pc3 | `deploy/levantar.sh <red>` | `clasificacion` y `busqueda` **healthy** |
   | 3 | pc2 | `deploy/levantar.sh <red>` | `ingesta` **healthy** |
   | 4 | pc1 | `deploy/levantar.sh <red>` | `gateway` y `usuarios` **healthy** |

   La primera vez cada PC construye sus imágenes: puede tardar varios minutos (Notificaciones, en pc4, es la más lenta).

3. Desde **pc1** (la que habla con todas), revisa la red completa:

   ```bash
   deploy/revisar_red.sh <red>
   ```

   Debe terminar con `Todo OK: 19 pruebas.` Si no, cada fallo trae una línea que dice qué revisar.

## 8. Orden de pruebas

Haz las pruebas en este orden: cada paso supone que el anterior pasó. `PC1_IP`, `PC4_IP`, etc. son las de tu `.env.<red>`.

### 8.1 Red

Ejecuta `deploy/revisar_red.sh <red>` **en las 4 PCs**: cada una revisa que llega a las demás. Todas deben dar `Todo OK`. Lo más importante: pc1 llega a todos los puertos y pc1, pc2 y pc3 llegan a `PC4_IP:5672`.

### 8.2 Estado por el gateway

Desde cualquier PC:

```bash
curl -s http://<PC1_IP>:8080/api/status
```

Debe decir `"status": "ok"` con los 5 servicios en `ok`.

### 8.3 Token interno

Una petición directa a un servicio, sin pasar por el gateway, debe ser rechazada; su `/health` sigue libre:

```bash
curl -i http://<PC2_IP>:8001/api/sources     # 403 {"detail": "token interno inválido"}
curl -i http://<PC2_IP>:8001/health          # 200
```

### 8.4 Aplicación y panel

1. Desde cualquier equipo de la red abre `http://<PC1_IP>:3000`.
2. Inicia sesión con `ADMIN_EMAIL` / `ADMIN_PASSWORD` de `.env.distribuido` y abre **Panel**: los 5 servicios, RabbitMQ (8 colas quorum) y el frontend deben estar en verde.

### 8.5 Flujo completo (demo)

1. En otra ventana (o en otro equipo), crea una cuenta de usuario y elige categorías, por ejemplo **Deportes**.
2. Como administrador, en **Fuentes → Agregar fuente**, agrega un feed nuevo (por ejemplo uno de `clasificacion/data/feeds.csv` que no esté en la lista) y pulsa **Scrapear**.
3. En pocos segundos las noticias deben aparecer en el **Feed** del usuario sin recargar, con su latencia, y en **Buscar**.

Ese recorrido cruza las 4 PCs: Ingesta (pc2) → RabbitMQ (pc4) → Clasificación (pc3) → Búsqueda (pc3) y Notificaciones (pc4) → gateway (pc1) → navegador.

### 8.6 Pruebas automáticas (opcional)

Los scripts de `verificacion/scripts/` funcionan en el modo distribuido con variables de entorno. Ejecútalos **desde pc4**: algunos leen las colas con `docker exec` sobre el contenedor local de RabbitMQ.

```bash
python3 -m venv /tmp/newsproject-verificacion/venv
/tmp/newsproject-verificacion/venv/bin/pip install aio-pika websockets==13.1 httpx PyJWT

set -a; . ./.env.distribuido; . ./.env.<red>; set +a     # carga claves e IPs en esta terminal
export NP_REPO="$PWD"
export NP_ENV_FILE="$PWD/.env.distribuido"
export NP_GATEWAY="http://$PC1_IP:8080"
export NP_AMQP_URL="amqp://$RABBITMQ_USER:$RABBITMQ_PASS@$PC4_IP:5672/"
export NP_RABBITMQ_CONTAINER=newsproject-dist-rabbitmq

cd verificacion/scripts
for t in test_auth test_ingesta test_clasif_busqueda test_notificaciones test_backfill test_productores_tras_reinicio; do
  /tmp/newsproject-verificacion/venv/bin/python $t.py
done
```

Cada línea debe empezar con `PASS`. Dos detalles:

- `test_ingesta` espera las **4 fuentes iniciales** y `test_productores_tras_reinicio` agrega una fuente fija: corren bien sobre datos nuevos. Si ya agregaste fuentes o los corriste antes, esas dos pruebas fallan aunque el sistema esté bien.
- `test_tolerancia`, `test_panel_admin`, `test_limpieza` y las pruebas de navegador son solo del modo de una PC (usan `docker compose` del proyecto `newsproject` o `localhost:3000`).

### 8.7 Tolerancia a fallos

1. En **pc3**: `deploy/levantar.sh <red> stop`. En el **Panel**, Clasificación y Búsqueda pasan a rojo y la cola `clasificacion.article-ingested` acumula mensajes si se scrapea. El resto de la app sigue funcionando (Buscar responde `503` con un mensaje claro).
2. En **pc3**: `deploy/levantar.sh <red> start`. En menos de un minuto vuelven a verde, la cola baja a 0 y las noticias pendientes llegan al feed.
3. Lo mismo con **pc4** (`stop` y `start`): todos los servicios marcan RabbitMQ sin conexión y se reconectan solos al volver.

## 9. Comandos del día a día

Todos se ejecutan en la PC correspondiente; `levantar.sh` pasa a `docker compose` lo que pongas después de la red.

```bash
deploy/levantar.sh <red>                 # construir y levantar (up -d --build)
deploy/levantar.sh <red> ps -a           # estado de los contenedores de esta PC
deploy/levantar.sh <red> logs -f         # logs de esta PC (o: logs -f busqueda)
deploy/levantar.sh <red> stop            # detener sin borrar nada
deploy/levantar.sh <red> start           # volver a iniciar
deploy/levantar.sh <red> down            # quitar contenedores (conserva los datos)
deploy/levantar.sh <red> down -v         # quitar contenedores y BORRAR los datos de esta PC
deploy/revisar_red.sh <red>              # revisar red, puertos y /health
```

- **Después de `git pull`**, vuelve a ejecutar `deploy/levantar.sh <red>` en cada PC para reconstruir; las 4 deben quedar en el mismo commit.
- Cada PC guarda solo los datos de sus servicios (volúmenes `newsproject-dist_*`). Para empezar desde cero hay que hacer `down -v` en **las 4 PCs**, y levantar de nuevo empezando por pc4.
- Los datos del modo distribuido y los del modo de una PC están en volúmenes distintos: uno no borra al otro.

## 10. Problemas comunes

**`levantar.sh: falta .../.env.pc (cópialo de .env.pc.example y edítalo)`** (o `.env.distribuido`, `.env.switch`, `.env.tailscale`)
Falta crear la copia de ese archivo en esta PC (sección 4).

**`AVISO: esta PC no tiene la IP 192.168.50.1x`** y luego `docker compose up` falla con `cannot assign requested address`
Docker solo puede publicar puertos en una IP que la PC tenga. Revisa, en este orden: que `.env.pc` diga la PC correcta, que `ip -4 addr` (o `tailscale ip -4`) muestre esa IP y que `.env.<red>` tenga la IP correcta. Con switch, puede que la IP fija no se aplicó o que el DHCP cambió la IP; con Tailscale, que `tailscale up` no esté activo.

**Después de reiniciar una PC, sus contenedores no arrancan**
Al encender, Docker puede arrancar antes de que la red (o Tailscale) tenga la IP, y el contenedor no puede publicar sus puertos. Espera a tener red (`ip -4 addr` o `tailscale status`) y ejecuta de nuevo `deploy/levantar.sh <red>`. Si Docker no está activo: `sudo systemctl start docker`.

**`Bind for 0.0.0.0:8080 failed: port is already allocated`** (o 3000, 5672, 15672)
El modo de una PC u otro programa usa ese puerto. Detén el modo de una PC con `docker compose stop` (o el otro programa) y vuelve a levantar.

**`revisar_red.sh`: `nada escucha en IP:puerto` aunque el contenedor está arriba**
Si `deploy/levantar.sh <red> ps` en esa PC muestra el contenedor `Up`, es el firewall. Abre el puerto en **esa** PC:

```bash
# Fedora / Nobara (firewalld)
sudo firewall-cmd --permanent --add-port=8001/tcp && sudo firewall-cmd --reload
# Ubuntu (ufw)
sudo ufw allow 8001/tcp
```

Puertos por PC: pc1 `3000 8080 8004`, pc2 `8001`, pc3 `8002 8003`, pc4 `5672 15672 8005`.

**`revisar_red.sh`: `no responde al ping`**
Revisa cable y switch (o `tailscale status`), que la IP de `.env.<red>` sea la de esa PC y que su firewall no bloquee el ping. Si el ping falla pero los puertos responden, solo está bloqueado ICMP y puedes seguir.

**Un servicio queda `unhealthy` y su `/health` dice `"rabbitmq": {"status": "error"}`**
No llega a RabbitMQ en `PC4_IP:5672`. Revisa que pc4 esté levantada, que `rabbitmq-init` terminara con `Exited (0)` y que esa PC llegue al puerto (`deploy/revisar_red.sh <red>`). Los servicios reintentan solos; no hace falta reiniciarlos.

**En los logs: `ACCESS_REFUSED - Login was refused`**
`RABBITMQ_USER` o `RABBITMQ_PASS` no coinciden con los de pc4: el `.env.distribuido` no es igual en todas las PCs. Cópialo de nuevo y vuelve a levantar esa PC. Si cambiaste la clave **después** de levantar pc4 por primera vez, RabbitMQ conserva la anterior: o vuelves a la clave original o haces `deploy/levantar.sh <red> down -v` en pc4 (borra las colas) y lo levantas de nuevo.

**La app o el gateway responden `503 servicio <nombre> no disponible`**
El gateway (pc1) no llega a ese servicio. Ejecuta `deploy/revisar_red.sh <red>` en pc1: dirá si es la PC, el puerto o el `/health`.

**Un servicio responde `403 {"detail": "token interno inválido"}` a peticiones que pasan por el gateway**
`DISTRIBUTED_INTERNAL_TOKEN` no es igual en pc1 y en la PC de ese servicio. Copia el mismo `.env.distribuido` a las dos y vuelve a levantarlas. (Un `403` a una petición **directa**, sin el gateway, es lo esperado.)

**El feed no se actualiza en vivo, pero al recargar aparecen las alertas**
El WebSocket pasa por pc1 (Nginx → gateway) hasta Notificaciones en pc4:8005. Revisa que pc1 llegue a `PC4_IP:8005` con `revisar_red.sh` y mira `deploy/levantar.sh <red> logs gateway` en pc1 (`ws.upstream_unavailable`).

**Latencias negativas o enormes en el feed**
Los relojes de las PCs no coinciden. Activa la sincronización: `sudo timedatectl set-ntp true` y comprueba con `timedatectl`.

**Ingesta no trae noticias nuevas (fuentes con error)**
pc2 necesita internet para leer los feeds. Comprueba con `curl -sI https://www.eluniverso.com` en pc2.

**El panel muestra un servicio «Con problemas» por su DLQ**
Hay mensajes que no se pudieron procesar (por ejemplo, de las pruebas automáticas). Se vacían **en pc4**:
`docker exec newsproject-dist-rabbitmq rabbitmqctl purge_queue <cola>.dlq`

**Las PCs no tienen la misma versión del código**
Síntomas raros (campos que faltan, `403` inesperados en `/health`). Compara `git log -1 --oneline` en las 4, haz `git pull` donde falte y vuelve a ejecutar `deploy/levantar.sh <red>`.

## 11. Seguridad: token interno

En el modo de una PC los servicios no se publican fuera de Docker, y el gateway es el único que aplica los permisos (JWT, roles) y pasa `X-User-Id` / `X-User-Role` a cada servicio. En el modo distribuido los servicios **sí** se publican en la red, así que alguien podría llamarlos directamente y saltarse esos permisos. Para evitarlo:

- El gateway envía `X-Internal-Token` (el valor de `DISTRIBUTED_INTERNAL_TOKEN`) en cada petición REST, en los `/health` y en el WebSocket hacia Notificaciones, e ignora cualquier `X-Internal-Token` que mande el navegador.
- Cada servicio compara ese token y responde `403` si no coincide. `GET /health` queda libre para poder diagnosticar la red.
- En el modo de una PC la variable no existe (`INTERNAL_TOKEN` vacío) y nada cambia.

Recomendaciones:

- Usa una red de confianza (la LAN del grupo o la tailnet). No abras estos puertos a internet.
- El panel de RabbitMQ (`PC4_IP:15672`) queda visible en la red: usa claves reales en `.env.distribuido`, nunca las de ejemplo.
- Si el token se filtra, genera uno nuevo, cópialo a las 4 PCs y vuelve a ejecutar `deploy/levantar.sh <red>` en todas.
