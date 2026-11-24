#!/usr/bin/env bash
# Command-line way to start/stop the lab test servers (the Django UI does the
# same through its process manager). Servers run INSIDE the lab namespaces.
# Usage: sudo scripts/lab_services.sh start|stop|status
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lab_common.sh"
parse_dry_run "$@"
require_root

ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
RUN="$ROOT/data/run"; mkdir -p "$RUN" "$ROOT/data/received"
PY="${AEGISNET_PRIV_PYTHON:-$(command -v python3)}"

# name node module args...
SERVICES=(
  "tcp-b b communication.tcp_server --host 10.10.5.2 --port 9001"
  "udp-b b communication.udp_server --host 10.10.5.2 --port 9002"
  "tcp-c c communication.tcp_server --host 10.10.6.2 --port 9001"
  "udp-c c communication.udp_server --host 10.10.6.2 --port 9002"
  "http-b b communication.test_services http --host 10.10.5.2 --port 8080"
  "dns-b b communication.test_services dns --host 10.10.5.2 --port 5353"
  "tls-b b communication.test_services tls --host 10.10.5.2 --port 8443"
)

case "${ARGS[0]:-status}" in
  start)
    for row in "${SERVICES[@]}"; do
      read -r name node module args <<<"$row"
      read -r -a extra <<<"$args" || true
      pidfile="$RUN/${name}.pid"
      # shellcheck disable=SC2086
      (cd "$ROOT" && PYTHONPATH="$ROOT" nohup ip netns exec "${AEGIS_PREFIX}${node}" \
          "$PY" -u -m "$module" $(echo "$row" | cut -d' ' -f4-) >"$RUN/${name}.log" 2>&1 & echo $! >"$pidfile")
      echo "started $name in ${AEGIS_PREFIX}${node}"
    done ;;
  stop)
    for f in "$RUN"/*.pid; do
      [[ -e "$f" ]] || continue
      kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"
    done
    echo "services stopped" ;;
  status)
    for f in "$RUN"/*.pid; do
      [[ -e "$f" ]] || continue
      if kill -0 "$(cat "$f")" 2>/dev/null; then echo "running  $(basename "$f" .pid)"; else echo "dead     $(basename "$f" .pid)"; fi
    done ;;
  *) echo "usage: lab_services.sh start|stop|status" >&2; exit 2 ;;
esac
