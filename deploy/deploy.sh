#!/usr/bin/env bash
# Server-side deploy for ClipAwesome. Run from an unpacked source tree (the GitHub workflow does this).
# Inputs (env): CLIPAWESOME_AUTH_PASSWORD (required), CLIPAWESOME_AUTH_USER, CLIPAWESOME_DOMAIN,
#               NGINX_CONTAINER, NGINX_NETWORK (optional overrides for auto-detection), DEPLOY_SHA.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SRC"

IMAGE=clipawesome
TAG=prod
HEALTH_TRIES=18
HEALTH_WAIT=10

log()  { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- preflight
log "Preflight"
command -v docker >/dev/null || die "docker is not installed"
docker info >/dev/null 2>&1 || die "this user cannot talk to the docker daemon"
docker compose version >/dev/null 2>&1 || die "docker compose v2 plugin is not installed"
DC=(docker compose)

[ -n "${CLIPAWESOME_AUTH_PASSWORD:-}" ] || die "CLIPAWESOME_AUTH_PASSWORD is empty"
case "$CLIPAWESOME_AUTH_PASSWORD${CLIPAWESOME_AUTH_USER:-}" in
  *"'"*|*$'\n'*) die "auth user/password must not contain single quotes or newlines" ;;
esac

docker_root="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /)"
free_kb="$(df -Pk "$docker_root" | awk 'NR==2 {print $4}')"
[ "${free_kb:-0}" -ge 4194304 ] || die "less than 4 GB free under $docker_root"
echo "docker: $(docker --version) | compose: ${DC[*]} | free: $((free_kb / 1024 / 1024)) GB"

# ---------------------------------------------------------------- .env
log "Writing .env"
umask 077
{
  grep -Ev '^[[:space:]]*(#|$)' .env.example
  printf "CLIPAWESOME_AUTH_USER='%s'\n" "${CLIPAWESOME_AUTH_USER:-admin}"
  printf "CLIPAWESOME_AUTH_PASSWORD='%s'\n" "$CLIPAWESOME_AUTH_PASSWORD"
} > .env
umask 022
HOST_PORT="$(sed -n 's/^CLIPAWESOME_HOST_PORT=//p' .env | tail -n1)"
HOST_PORT="${HOST_PORT:-8096}"

# ---------------------------------------------------------------- nginx / network detection
log "Detecting nginx"
NGINX_C="${NGINX_CONTAINER:-}"
if [ -z "$NGINX_C" ]; then
  NGINX_C="$(docker ps --format '{{.Names}} {{.Image}}' | awk 'tolower($0) ~ /nginx/ {print $1; exit}')"
fi

rm -f compose.proxy.yaml
UPSTREAM="http://127.0.0.1:${HOST_PORT}"
RESOLVER=""
NGINX_MODE=none

if [ -n "$NGINX_C" ]; then
  docker inspect "$NGINX_C" >/dev/null 2>&1 || die "nginx container '$NGINX_C' not found"
  NGINX_MODE=container
  NET="${NGINX_NETWORK:-}"
  if [ -z "$NET" ]; then
    NET="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' "$NGINX_C" \
           | grep -Ev '^(bridge|host|none)?$' | head -n1 || true)"
  fi
  if [ -n "$NET" ]; then
    echo "nginx container: $NGINX_C, joining network: $NET (alias 'clipawesome')"
    cat > compose.proxy.yaml <<EOF
services:
  app:
    networks:
      default: {}
      edge:
        aliases: [clipawesome]
networks:
  edge:
    external: true
    name: ${NET}
EOF
    UPSTREAM="http://clipawesome:8765"
    RESOLVER="resolver 127.0.0.11 valid=10s ipv6=off;"
  elif docker inspect -f '{{.HostConfig.NetworkMode}}' "$NGINX_C" | grep -qx host; then
    echo "nginx container $NGINX_C uses host networking -> upstream $UPSTREAM"
  else
    NGINX_MODE=unreachable
    warn "nginx container $NGINX_C is only on the default bridge; set the NGINX_NETWORK variable to a shared network"
  fi
elif command -v systemctl >/dev/null && systemctl is-active --quiet nginx; then
  NGINX_MODE=host
  echo "host nginx detected -> upstream $UPSTREAM"
else
  echo "no nginx found; app will listen on 127.0.0.1:${HOST_PORT} only"
fi

COMPOSE=("${DC[@]}" -p clipawesome --env-file .env -f compose.yaml)
[ -f compose.proxy.yaml ] && COMPOSE+=(-f compose.proxy.yaml)

# ---------------------------------------------------------------- build
log "Building image"
HAVE_ROLLBACK=0
if docker image inspect "$IMAGE:$TAG" >/dev/null 2>&1; then
  docker tag "$IMAGE:$TAG" "$IMAGE:$TAG-rollback"
  HAVE_ROLLBACK=1
fi
"${COMPOSE[@]}" build --pull

# ---------------------------------------------------------------- start + health
wait_healthy() {
  local cid status i
  cid="$("${COMPOSE[@]}" ps -q app)"
  [ -n "$cid" ] || return 1
  for i in $(seq 1 "$HEALTH_TRIES"); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo missing)"
    echo "health check $i/$HEALTH_TRIES: $status"
    case "$status" in
      healthy) return 0 ;;
      unhealthy|exited|dead|missing) return 1 ;;
    esac
    sleep "$HEALTH_WAIT"
  done
  return 1
}

log "Starting container"
"${COMPOSE[@]}" up -d --remove-orphans

if ! wait_healthy; then
  warn "new release is unhealthy; recent logs:"
  "${COMPOSE[@]}" logs --tail 80 app || true
  if [ "$HAVE_ROLLBACK" = 1 ]; then
    log "Rolling back"
    docker tag "$IMAGE:$TAG-rollback" "$IMAGE:$TAG"
    "${COMPOSE[@]}" up -d --no-build --force-recreate
    wait_healthy && echo "rollback is healthy" || warn "rollback is not healthy either"
  fi
  die "deployment failed"
fi

# ---------------------------------------------------------------- nginx vhost (optional)
put_file() {  # put_file <src> <dest>  — plain copy, else passwordless sudo
  cp "$1" "$2" 2>/dev/null || sudo -n cp "$1" "$2" 2>/dev/null
}
drop_file() { rm -f "$1" 2>/dev/null || sudo -n rm -f "$1" 2>/dev/null || true; }

install_vhost() {
  local domain="$1" conf_dir="" rendered backup="" target
  [[ "$domain" =~ ^[A-Za-z0-9.-]+$ ]] || { warn "invalid CLIPAWESOME_DOMAIN '$domain'"; return 1; }

  case "$NGINX_MODE" in
    container) conf_dir="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/nginx/conf.d"}}{{.Source}}{{end}}{{end}}' "$NGINX_C")" ;;
    host)      conf_dir=/etc/nginx/conf.d ;;
  esac
  [ -n "$conf_dir" ] && [ -d "$conf_dir" ] || { warn "nginx conf.d directory not found on the host"; return 1; }

  rendered="$(mktemp)"
  sed -e "s|__SERVER_NAME__|$domain|" -e "s|__PROXY_TARGET__|$UPSTREAM|" -e "s|__RESOLVER__|$RESOLVER|" \
      deploy/nginx/clipawesome.conf.template > "$rendered"
  chmod 644 "$rendered"
  target="$conf_dir/clipawesome.conf"
  if [ -f "$target" ]; then
    cmp -s "$rendered" "$target" && { echo "vhost unchanged"; rm -f "$rendered"; return 0; }
    backup="$(mktemp)"; cp "$target" "$backup"
  fi
  put_file "$rendered" "$target" || { warn "no permission to write $target"; rm -f "$rendered"; return 1; }
  rm -f "$rendered"

  local test_cmd reload_cmd
  if [ "$NGINX_MODE" = container ]; then
    test_cmd=(docker exec "$NGINX_C" nginx -t); reload_cmd=(docker exec "$NGINX_C" nginx -s reload)
  else
    test_cmd=(sudo -n nginx -t); reload_cmd=(sudo -n systemctl reload nginx)
  fi
  if "${test_cmd[@]}" && "${reload_cmd[@]}"; then
    echo "vhost installed at $target for $domain"
    [ -n "$backup" ] && rm -f "$backup"
    return 0
  fi
  warn "nginx rejected the vhost; reverting"
  if [ -n "$backup" ]; then put_file "$backup" "$target"; rm -f "$backup"; else drop_file "$target"; fi
  "${test_cmd[@]}" >/dev/null 2>&1 && "${reload_cmd[@]}" >/dev/null 2>&1 || true
  return 1
}

if [ -n "${CLIPAWESOME_DOMAIN:-}" ]; then
  log "Configuring nginx for $CLIPAWESOME_DOMAIN"
  if [ "$NGINX_MODE" != container ] && [ "$NGINX_MODE" != host ]; then
    warn "CLIPAWESOME_DOMAIN is set but no reachable nginx was found; skipping vhost"
  elif ! install_vhost "$CLIPAWESOME_DOMAIN"; then
    warn "vhost not installed; see docs/DEPLOYMENT.md to add it by hand (app itself is running)"
  fi
else
  echo "CLIPAWESOME_DOMAIN not set; nginx config left untouched (upstream would be $UPSTREAM)"
fi

# ---------------------------------------------------------------- cleanup
log "Cleanup"
[ "$HAVE_ROLLBACK" = 1 ] && docker rmi "$IMAGE:$TAG-rollback" >/dev/null 2>&1 || true
docker image prune -f >/dev/null || true

log "Deployed ${DEPLOY_SHA:-unknown revision} on 127.0.0.1:${HOST_PORT}"
