#!/usr/bin/env bash
# Revisa la red del modo distribuido desde esta PC: alcance de cada PC, puerto de cada
# componente y GET /health donde existe. Muestra una tabla OK/FALLA y explica cada fallo.
#
# Uso:
#   deploy/revisar_red.sh <switch|tailscale>
#
# Lee .env.switch o .env.tailscale (PC1_IP ... PC4_IP) desde la raíz del repositorio;
# DEPLOY_ENV_DIR permite leerlo desde otra carpeta. Sale con 0 si todo está OK y con 1 si no.
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR_ENV="${DEPLOY_ENV_DIR:-$RAIZ}"

uso() { echo "Uso: deploy/revisar_red.sh <switch|tailscale>" >&2; exit 2; }

leer_var() {
  local archivo="$1" clave="$2" valor
  valor="$(grep -E "^[[:space:]]*${clave}[[:space:]]*=" "$archivo" | tail -n 1 | cut -d= -f2- || true)"
  valor="${valor%%#*}"
  valor="$(echo "$valor" | tr -d "\"' \t\r")"
  printf '%s' "$valor"
}

[[ $# -eq 1 ]] || uso
RED="$1"
case "$RED" in switch|tailscale) ;; *) uso ;; esac
ENV_RED="$DIR_ENV/.env.$RED"
[[ -f "$ENV_RED" ]] || { echo "revisar_red.sh: falta $ENV_RED (cópialo de .env.$RED.example)" >&2; exit 2; }

declare -A IP INALCANZABLE
for pc in pc1 pc2 pc3 pc4; do
  IP[$pc]="$(leer_var "$ENV_RED" "${pc^^}_IP")"
  [[ -n "${IP[$pc]}" ]] || { echo "revisar_red.sh: falta ${pc^^}_IP en $ENV_RED" >&2; exit 2; }
done

# componente|pc|puerto|ruta de health ("-" = solo puerto)|perfil
COMPONENTES=(
  "gateway|pc1|8080|/health|entrada"
  "frontend|pc1|3000|-|entrada"
  "usuarios|pc1|8004|/health|usuarios"
  "ingesta|pc2|8001|/health|ingesta"
  "clasificacion|pc3|8002|/health|clasificacion"
  "busqueda|pc3|8003|/health|busqueda"
  "rabbitmq (AMQP)|pc4|5672|-|broker"
  "rabbitmq (panel)|pc4|15672|-|broker"
  "notificaciones|pc4|8005|/health|notificaciones"
)

FILAS=()     # "prueba|destino|resultado"
FALLOS=()    # una línea por fallo

fila() { FILAS+=("$1|$2|$3"); }
fallo() { FALLOS+=("$1"); }

es_ip_local() { command -v ip >/dev/null 2>&1 && ip -o -4 addr show | grep -qF " $1/"; }

# 1) Alcance de cada PC
for pc in pc1 pc2 pc3 pc4; do
  ip="${IP[$pc]}"
  if es_ip_local "$ip"; then
    fila "$pc alcanzable" "$ip" "OK (esta PC)"
    continue
  fi
  if [[ "$RED" == tailscale ]]; then
    if ! command -v tailscale >/dev/null 2>&1; then
      fila "$pc tailscale ping" "$ip" "FALLA"; INALCANZABLE[$pc]=1
      fallo "$pc ($ip): no está el comando tailscale en esta PC; instálalo y ejecuta 'sudo tailscale up'."
    elif tailscale ping -c 1 --timeout 3s "$ip" >/dev/null 2>&1; then
      fila "$pc tailscale ping" "$ip" "OK"
    else
      fila "$pc tailscale ping" "$ip" "FALLA"; INALCANZABLE[$pc]=1
      fallo "$pc ($ip): no responde a tailscale ping; revisa que esa PC tenga 'tailscale up', esté en la misma tailnet y que la IP 100.x sea la de 'tailscale ip -4'."
    fi
  else
    if ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then
      fila "$pc ping" "$ip" "OK"
    else
      fila "$pc ping" "$ip" "FALLA"; INALCANZABLE[$pc]=1
      fallo "$pc ($ip): no responde al ping; revisa cable y switch, que la IP de $ENV_RED sea la de esa PC (ip -4 addr) y que su firewall no bloquee ICMP."
    fi
  fi
done

# 2) Puerto y /health de cada componente
for c in "${COMPONENTES[@]}"; do
  IFS='|' read -r nombre pc puerto ruta perfil <<<"$c"
  ip="${IP[$pc]}"
  destino="$ip:$puerto"
  if ! timeout 3 bash -c "exec 3<>/dev/tcp/$ip/$puerto" 2>/dev/null; then
    fila "$nombre ($pc) puerto" "$destino" "FALLA"
    if [[ -n "${INALCANZABLE[$pc]:-}" ]]; then
      fallo "$nombre: sin respuesta en $destino porque $pc no es alcanzable (ver el fallo de $pc); resuelve eso primero."
    else
      fallo "$nombre: nada escucha en $destino; levanta el perfil '$perfil' en $pc (deploy/levantar.sh $RED) o abre el puerto $puerto/tcp en su firewall."
    fi
    [[ "$ruta" != "-" ]] && fila "$nombre ($pc) GET $ruta" "$destino" "FALLA"
    continue
  fi
  fila "$nombre ($pc) puerto" "$destino" "OK"
  [[ "$ruta" == "-" ]] && continue

  cuerpo="$(curl -s --connect-timeout 3 -m 5 -w $'\n%{http_code}' "http://$destino$ruta" 2>/dev/null)"
  codigo="${cuerpo##*$'\n'}"
  cuerpo="${cuerpo%$'\n'*}"
  if [[ "$codigo" == 200 ]]; then
    fila "$nombre ($pc) GET $ruta" "$destino" "OK"
    continue
  fi
  fila "$nombre ($pc) GET $ruta" "$destino" "FALLA"
  # Qué check falló, según el formato común de /health (checks.db, checks.rabbitmq)
  malos="$(printf '%s' "$cuerpo" | python3 -c 'import json,sys
try:
    c = json.load(sys.stdin).get("checks", {})
    print(" y ".join({"db": "su base de datos", "rabbitmq": "RabbitMQ"}.get(k, k) for k, v in c.items() if v.get("status") != "ok"))
except Exception:
    pass' 2>/dev/null)"
  case "$codigo" in
    000) fallo "$nombre: el puerto $destino abre pero GET $ruta no responde a tiempo; el servicio sigue arrancando o está colgado (docker logs en $pc)." ;;
    503) if [[ "$malos" == *RabbitMQ* ]]; then
           fallo "$nombre: GET $ruta = 503, sin conexión a ${malos}; revisa que pc4 (${IP[pc4]}:5672) esté arriba y alcanzable desde $pc y que rabbitmq-init terminara."
         elif [[ -n "$malos" ]]; then
           fallo "$nombre: GET $ruta = 503, falla ${malos}; mira 'docker logs' del servicio en $pc."
         else
           fallo "$nombre: GET $ruta = 503 (servicio no listo); espera el arranque o mira 'docker logs' en $pc."
         fi ;;
    403) fallo "$nombre: GET $ruta = 403; /health no debería pedir token, revisa que $pc tenga la versión actual del código." ;;
    *)   fallo "$nombre: GET $ruta = HTTP $codigo; respuesta inesperada, mira 'docker logs' del servicio en $pc." ;;
  esac
done

# 3) Tabla y explicación
echo "Red: $RED ($ENV_RED) · revisado desde $(hostname)"
echo
printf '%-34s %-22s %s\n' "PRUEBA" "DESTINO" "RESULTADO"
printf '%-34s %-22s %s\n' "------" "-------" "---------"
for f in "${FILAS[@]}"; do
  IFS='|' read -r prueba destino resultado <<<"$f"
  printf '%-34s %-22s %s\n' "$prueba" "$destino" "$resultado"
done
echo
if [[ ${#FALLOS[@]} -eq 0 ]]; then
  echo "Todo OK: ${#FILAS[@]} pruebas."
  exit 0
fi
echo "${#FALLOS[@]} fallo(s):"
for f in "${FALLOS[@]}"; do echo "  - $f"; done
exit 1
