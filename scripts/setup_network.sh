#!/usr/bin/env bash
# Create the isolated AegisNet test network (6 namespaces, 6 veth links).
# Usage: sudo scripts/setup_network.sh [--dry-run]
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lab_common.sh"
parse_dry_run "$@"
require_root

if (( ! DRY )); then
  for n in "${NODES[@]}"; do
    if ns_exists "$n"; then
      echo "ERROR: namespace ${AEGIS_PREFIX}${n} already exists. Run cleanup_network.sh first." >&2
      exit 2
    fi
  done
fi

echo "== 1. creating namespaces"
for n in "${NODES[@]}"; do
  run ip netns add "${AEGIS_PREFIX}${n}"
  nsx "$n" ip link set lo up
done

echo "== 2. enabling IP forwarding on routers (inside their namespace only)"
for r in "${ROUTERS[@]}"; do
  nsx "$r" sh -c 'echo 1 > /proc/sys/net/ipv4/ip_forward'
  # recovery may use asymmetric paths; do not let reverse-path filtering drop them
  nsx "$r" sh -c 'echo 0 > /proc/sys/net/ipv4/conf/all/rp_filter; echo 0 > /proc/sys/net/ipv4/conf/default/rp_filter'
done

echo "== 3. creating veth pairs and addressing them"
for row in "${LINKS[@]}"; do
  read -r name a b ifa ifb ipa ipb <<<"$row"
  run ip link add "$ifa" type veth peer name "$ifb"
  run ip link set "$ifa" netns "${AEGIS_PREFIX}${a}"
  run ip link set "$ifb" netns "${AEGIS_PREFIX}${b}"
  nsx "$a" ip addr add "${ipa}/30" dev "$ifa"
  nsx "$b" ip addr add "${ipb}/30" dev "$ifb"
  nsx "$a" ip link set "$ifa" up
  nsx "$b" ip link set "$ifb" up
  echo "   link ${name}: ${a}:${ifa}=${ipa}  <->  ${b}:${ifb}=${ipb}"
done

echo "== 4. installing baseline static routes (primary path A-R1-R2-B)"
apply_routes

echo "== done. Verify with: sudo scripts/verify_network.sh"
