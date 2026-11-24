#!/usr/bin/env bash
# Add controlled impairment to one lab link (tc netem / tbf) - used to make TCP
# and UDP behave differently, or to create congestion for the ML dataset.
# Usage: sudo scripts/impair_link.sh <link-name> loss <percent>
#        sudo scripts/impair_link.sh <link-name> delay <ms>
#        sudo scripts/impair_link.sh <link-name> rate <mbit>
#        sudo scripts/impair_link.sh <link-name> clear
# Requires the kernel modules sch_netem / sch_tbf; a clear error is printed if
# they are missing (nothing is faked).
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lab_common.sh"
parse_dry_run "$@"
require_root

LINK="${ARGS[0]:-}"; KIND="${ARGS[1]:-}"; VALUE="${ARGS[2]:-}"
find_link "$LINK" || { echo "ERROR: unknown lab link '$LINK'" >&2; exit 2; }
if [[ -n "$VALUE" && ! "$VALUE" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
  echo "ERROR: value must be a number" >&2; exit 2
fi

apply() { # apply <node> <iface> <tc args...>
  local node="$1" iface="$2"; shift 2
  nsx "$node" tc qdisc replace dev "$iface" root "$@"
}

case "$KIND" in
  loss)  for e in "$L_A $L_IFA" "$L_B $L_IFB"; do set -- $e; apply "$1" "$2" netem loss "${VALUE}%"; done ;;
  delay) for e in "$L_A $L_IFA" "$L_B $L_IFB"; do set -- $e; apply "$1" "$2" netem delay "${VALUE}ms"; done ;;
  rate)  for e in "$L_A $L_IFA" "$L_B $L_IFB"; do set -- $e; apply "$1" "$2" tbf rate "${VALUE}mbit" burst 32kbit latency 50ms; done ;;
  clear)
    if (( DRY )); then echo "[dry-run] tc qdisc del on ${L_IFA} and ${L_IFB}"; else
      ip netns exec "${AEGIS_PREFIX}${L_A}" tc qdisc del dev "$L_IFA" root 2>/dev/null || true
      ip netns exec "${AEGIS_PREFIX}${L_B}" tc qdisc del dev "$L_IFB" root 2>/dev/null || true
    fi ;;
  *) echo "usage: impair_link.sh <link> loss|delay|rate <value> | clear" >&2; exit 2 ;;
esac
echo "impairment '${KIND}' ${VALUE} applied to ${LINK}"
