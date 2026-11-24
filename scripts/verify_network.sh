#!/usr/bin/env bash
# Verify connectivity of the lab: every link neighbour and the three host pairs.
# Usage: sudo scripts/verify_network.sh        (exit code 0 only if all pass)
set -uo pipefail
source "$(dirname "$(readlink -f "$0")")/lab_common.sh"
parse_dry_run "$@"
require_root

FAIL=0
check() { # check <from-node> <ip> <label>
  if ip netns exec "${AEGIS_PREFIX}$1" ping -n -c 2 -W 1 "$2" >/dev/null 2>&1; then
    printf '  PASS  %-28s %s -> %s\n' "$3" "$1" "$2"
  else
    printf '  FAIL  %-28s %s -> %s\n' "$3" "$1" "$2"; FAIL=1
  fi
}

echo "Link neighbour checks"
for row in "${LINKS[@]}"; do
  read -r name a b ifa ifb ipa ipb <<<"$row"
  check "$a" "$ipb" "link $name"
done
echo "End-to-end host checks"
check a 10.10.5.2 "PC A -> PC B"
check a 10.10.6.2 "PC A -> PC C"
check b 10.10.6.2 "PC B -> PC C"
check c 10.10.1.1 "PC C -> PC A"
exit $FAIL
