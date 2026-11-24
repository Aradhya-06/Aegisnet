#!/usr/bin/env bash
# Generate traffic between lab nodes so the packet analyzer has something to see.
# Needs the servers from lab_services.sh. Usage: sudo scripts/generate_traffic.sh
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lab_common.sh"
require_root
ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
PY="${AEGISNET_PRIV_PYTHON:-$(command -v python3)}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
X() { ip netns exec "${AEGIS_PREFIX}a" "$@"; }

echo "ICMP";  X ping -n -c 3 10.10.5.2 >/dev/null
echo "TCP";   X "$PY" -m communication.client --proto tcp --host 10.10.5.2 --port 9001 --message "hello over TCP"
echo "UDP";   X "$PY" -m communication.client --proto udp --host 10.10.5.2 --port 9002 --message "hello over UDP" --count 3
echo "HTTP";  X "$PY" -m communication.traffic http --host 10.10.5.2 --port 8080
echo "DNS";   X "$PY" -m communication.traffic dns --host 10.10.5.2 --port 5353 --name aegisnet.lab
echo "TLS";   X "$PY" -m communication.traffic tls --host 10.10.5.2 --port 8443
