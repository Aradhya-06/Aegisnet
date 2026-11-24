#!/usr/bin/env bash
# Roll back: bring links up, remove traffic impairments, re-install baseline routes.
# Usage: sudo scripts/restore_network.sh [all|<link-name>] [--dry-run]
# Restoring re-applies the baseline route table, which also undoes any route
# change made by the recovery engine.
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lab_common.sh"
parse_dry_run "$@"
require_root

TARGET="${ARGS[0]:-all}"
restore_one() {
  find_link "$1" || { echo "ERROR: unknown link $1" >&2; exit 2; }
  echo "Bringing link ${L_NAME} UP"
  nsx "$L_A" ip link set "$L_IFA" up
  nsx "$L_B" ip link set "$L_IFB" up
  # clear any tc impairment (ignore 'no qdisc' errors)
  if (( DRY )); then
    echo "[dry-run] tc qdisc del dev ${L_IFA} root (in ${L_A}) / ${L_IFB} (in ${L_B})"
  else
    ip netns exec "${AEGIS_PREFIX}${L_A}" tc qdisc del dev "$L_IFA" root 2>/dev/null || true
    ip netns exec "${AEGIS_PREFIX}${L_B}" tc qdisc del dev "$L_IFB" root 2>/dev/null || true
  fi
}

if [[ "$TARGET" == "all" ]]; then
  for row in "${LINKS[@]}"; do
    read -r name _ <<<"$row"
    restore_one "$name"
  done
else
  restore_one "$TARGET"
fi

echo "Re-applying baseline routes"
apply_routes
echo "restore complete"
