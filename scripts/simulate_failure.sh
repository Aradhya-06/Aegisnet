#!/usr/bin/env bash
# Controlled failure injection: bring ONE lab link down (both ends).
# Usage: sudo scripts/simulate_failure.sh <link-name> [--dry-run]
#   link-name is one of: a-r1 r1-r2 r1-r3 r3-r2 r2-b r3-c
# Only interfaces inside aegis_* namespaces can be touched: the link name is
# looked up in the lab table, anything else is refused.
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lab_common.sh"
parse_dry_run "$@"
require_root

LINK="${ARGS[0]:-}"
if [[ -z "$LINK" ]] || ! find_link "$LINK"; then
  echo "ERROR: unknown lab link '${LINK}'. Valid: a-r1 r1-r2 r1-r3 r3-r2 r2-b r3-c" >&2
  exit 2
fi
if (( ! DRY )) && ! ns_exists "$L_A"; then
  echo "ERROR: lab network is not set up (namespace ${AEGIS_PREFIX}${L_A} missing)." >&2
  exit 3
fi

echo "Bringing link ${L_NAME} DOWN (${L_A}:${L_IFA} and ${L_B}:${L_IFB})"
nsx "$L_A" ip link set "$L_IFA" down
nsx "$L_B" ip link set "$L_IFB" down
echo "failure injected: ${L_NAME}"
