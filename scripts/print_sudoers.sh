#!/usr/bin/env bash
# Prints the sudoers lines that let the web application (running as YOU) use the
# privileged helpers, and nothing else. Review them, then add with: sudo visudo -f /etc/sudoers.d/aegisnet
#
# Usage: scripts/print_sudoers.sh [python-path]
#   python-path defaults to the interpreter you pass (use the virtualenv python
#   that runs Django, because the helper imports your installed packages).
set -euo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
PY="${1:-$(command -v python3)}"
USER_NAME="${SUDO_USER:-$(id -un)}"
cat <<EOF
# --- AegisNet lab helpers for ${USER_NAME} ---
${USER_NAME} ALL=(root) NOPASSWD: ${PY} -I ${HERE}/ns_exec.py *, \\
    ${HERE}/setup_network.sh, ${HERE}/cleanup_network.sh, ${HERE}/verify_network.sh, \\
    ${HERE}/simulate_failure.sh *, ${HERE}/restore_network.sh *, ${HERE}/impair_link.sh *

# Also export this before starting Django so it calls exactly that interpreter:
#   export AEGISNET_PRIV_PYTHON=${PY}
# WARNING: ns_exec.py runs project code as root. Only do this on a VM / personal lab
# machine where you are the only user.
EOF
