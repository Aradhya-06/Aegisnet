#!/usr/bin/env bash
# Remove EVERYTHING AegisNet created: processes in the lab namespaces, the
# namespaces themselves (their veth ends vanish with them). Only names from the
# lab table (aegis_a ... aegis_c) are ever deleted.
# Usage: sudo scripts/cleanup_network.sh [--dry-run]
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lab_common.sh"
parse_dry_run "$@"
require_root

for n in "${NODES[@]}"; do
  ns="${AEGIS_PREFIX}${n}"
  if (( DRY )); then
    echo "[dry-run] kill processes in ${ns}; ip netns del ${ns}"
    continue
  fi
  if ns_exists "$n"; then
    pids="$(ip netns pids "$ns" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      echo "stopping processes in ${ns}: ${pids//$'\n'/ }"
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      sleep 0.3
    fi
    ip netns del "$ns"
    echo "deleted ${ns}"
  fi
done
echo "cleanup complete"
