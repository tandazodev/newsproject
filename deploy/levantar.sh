#!/usr/bin/env bash
# Levanta en esta PC su parte del modo distribuido (docker-compose.distribuido.yml).
#
# Uso:
#   deploy/levantar.sh <switch|tailscale>                 # docker compose up -d --build
#   deploy/levantar.sh <switch|tailscale> <comando...>    # otro comando de compose: ps, logs -f, down, config...
#
# Lee, desde la raíz del repositorio:
#   .env.distribuido                  claves (iguales en las 4 PCs)
#   .env.switch o .env.tailscale      IP de cada PC (PC1_IP ... PC4_IP)
#   .env.pc                           PC=pc1|pc2|pc3|pc4 (qué PC es esta)
# DEPLOY_ENV_DIR permite leerlos desde otra carpeta.
#
# Reparto:
#   pc1: entrada (gateway + frontend) y usuarios
#   pc2: ingesta
#   pc3: clasificacion y busqueda
#   pc4: broker (rabbitmq + rabbitmq-init) y notificaciones
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR_ENV="${DEPLOY_ENV_DIR:-$RAIZ}"
COMPOSE_FILE="$RAIZ/docker-compose.distribuido.yml"

error() { echo "levantar.sh: $*" >&2; exit 1; }

uso() {
  echo "Uso: deploy/levantar.sh <switch|tailscale> [comando de docker compose...]" >&2
  exit 2
}

# Valor de una variable KEY=valor en un archivo .env (última aparición, sin comillas ni espacios).
leer_var() {
  local archivo="$1" clave="$2" valor
  valor="$(grep -E "^[[:space:]]*${clave}[[:space:]]*=" "$archivo" | tail -n 1 | cut -d= -f2- || true)"
  valor="${valor%%#*}"                       # quita comentario al final de la línea
  valor="$(echo "$valor" | tr -d "\"' \t\r")"
  printf '%s' "$valor"
}

exigir_archivo() {
  [[ -f "$1" ]] || error "falta $1 (cópialo de $(basename "$1").example y edítalo)"
}

[[ $# -ge 1 ]] || uso
RED="$1"; shift
case "$RED" in
  switch|tailscale) ;;
  *) uso ;;
esac

ENV_CLAVES="$DIR_ENV/.env.distribuido"
ENV_RED="$DIR_ENV/.env.$RED"
ENV_PC="$DIR_ENV/.env.pc"
for f in "$ENV_CLAVES" "$ENV_RED" "$ENV_PC"; do exigir_archivo "$f"; done

PC="$(leer_var "$ENV_PC" PC)"
case "$PC" in
  pc1) PERFILES=(entrada usuarios);           VAR_IP=PC1_IP ;;
  pc2) PERFILES=(ingesta);                    VAR_IP=PC2_IP ;;
  pc3) PERFILES=(clasificacion busqueda);     VAR_IP=PC3_IP ;;
  pc4) PERFILES=(broker notificaciones);      VAR_IP=PC4_IP ;;
  *) error "PC='$PC' en $ENV_PC no es válido: usa pc1, pc2, pc3 o pc4" ;;
esac

for v in PC1_IP PC2_IP PC3_IP PC4_IP; do
  [[ -n "$(leer_var "$ENV_RED" "$v")" ]] || error "falta $v en $ENV_RED"
done

MI_IP="$(leer_var "$ENV_RED" "$VAR_IP")"
[[ "$MI_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || error "$VAR_IP='$MI_IP' en $ENV_RED no es una IPv4"

# Docker solo puede publicar puertos en una IP que tenga esta PC: se avisa si no la tiene.
if command -v ip >/dev/null 2>&1 && ! ip -o -4 addr show | grep -qF " $MI_IP/"; then
  echo "levantar.sh: AVISO: esta PC no tiene la IP $MI_IP ($VAR_IP en $ENV_RED)." >&2
  echo "             Revisa .env.pc y la red ($RED); 'docker compose up' fallará al publicar puertos." >&2
fi

export MI_IP
ARGS_PERFILES=()
for p in "${PERFILES[@]}"; do ARGS_PERFILES+=(--profile "$p"); done

if [[ $# -eq 0 ]]; then
  set -- up -d --build
fi

echo "levantar.sh: $PC ($RED) · MI_IP=$MI_IP · perfiles: ${PERFILES[*]} · docker compose $*" >&2

exec docker compose \
  -f "$COMPOSE_FILE" \
  --project-directory "$RAIZ" \
  --env-file "$ENV_CLAVES" \
  --env-file "$ENV_RED" \
  "${ARGS_PERFILES[@]}" \
  "$@"
