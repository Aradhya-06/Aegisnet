#!/usr/bin/env bash
# =============================================================================
# AegisNet lab definition - SOURCED by the other scripts (do not run directly).
#
# One place that describes the isolated test network so that setup, failure,
# restore and cleanup always agree. The same table is mirrored in
# core/topology_def.py (a unit test checks the two stay identical).
#
#                 primary (cost 1)
#   PC A -- R1 ------------------- R2 -- PC B
#             \                   /
#              \--- R3 ----------/        backup path through R3
#                    |
#                  PC C
#
# SAFETY: every object created here lives inside a network namespace called
# aegis_<node>. The host's interfaces, default route and DNS are never touched.
# =============================================================================

AEGIS_PREFIX="aegis_"
NODES=(a r1 r2 r3 b c)
ROUTERS=(r1 r2 r3)

# name nodeA nodeB ifaceA ifaceB ipA ipB   (every link is a /30)
LINKS=(
  "a-r1 a r1 a-r1 r1-a 10.10.1.1 10.10.1.2"
  "r1-r2 r1 r2 r1-r2 r2-r1 10.10.2.1 10.10.2.2"
  "r1-r3 r1 r3 r1-r3 r3-r1 10.10.3.1 10.10.3.2"
  "r3-r2 r3 r2 r3-r2 r2-r3 10.10.4.1 10.10.4.2"
  "r2-b r2 b r2-b b-r2 10.10.5.1 10.10.5.2"
  "r3-c r3 c r3-c c-r3 10.10.6.1 10.10.6.2"
)

# Baseline static routes: node destination next-hop (primary path = via R2)
ROUTES=(
  "a default 10.10.1.2"
  "b default 10.10.5.1"
  "c default 10.10.6.1"
  "r1 10.10.4.0/30 10.10.2.2"
  "r1 10.10.5.0/30 10.10.2.2"
  "r1 10.10.6.0/30 10.10.3.2"
  "r2 10.10.1.0/30 10.10.2.1"
  "r2 10.10.3.0/30 10.10.2.1"
  "r2 10.10.6.0/30 10.10.4.1"
  "r3 10.10.1.0/30 10.10.3.1"
  "r3 10.10.2.0/30 10.10.3.1"
  "r3 10.10.5.0/30 10.10.4.2"
)

DRY=0

# strip --dry-run from the argument list, remember it
parse_dry_run() {
  ARGS=()
  for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then DRY=1; else ARGS+=("$arg"); fi
  done
}

require_root() {
  if [[ $DRY -eq 0 && $EUID -ne 0 ]]; then
    echo "ERROR: this script changes network namespaces and must run as root (use sudo)." >&2
    exit 1
  fi
}

# run a command, or only print it in dry-run mode
run() {
  if (( DRY )); then echo "[dry-run] $*"; else "$@"; fi
}

# run a command inside lab namespace aegis_<node>
nsx() {
  local node="$1"; shift
  run ip netns exec "${AEGIS_PREFIX}${node}" "$@"
}

ns_exists() {
  ip netns list 2>/dev/null | awk '{print $1}' | grep -qx "${AEGIS_PREFIX}$1"
}

# find_link <name>: sets L_NAME L_A L_B L_IFA L_IFB L_IPA L_IPB
find_link() {
  local row
  for row in "${LINKS[@]}"; do
    read -r L_NAME L_A L_B L_IFA L_IFB L_IPA L_IPB <<<"$row"
    if [[ "$L_NAME" == "$1" ]]; then return 0; fi
  done
  return 1
}

apply_routes() {
  local row node dest via
  for row in "${ROUTES[@]}"; do
    read -r node dest via <<<"$row"
    if [[ "$dest" == "default" ]]; then
      nsx "$node" ip route replace default via "$via"
    else
      nsx "$node" ip route replace "$dest" via "$via"
    fi
  done
}
