"""Run network commands safely, either on the host or inside a lab namespace.

All privileged work goes through scripts/ns_exec.py (allow-listed commands, lab
addresses only) or one of the lab scripts. Nothing here ever uses a shell.
"""
from __future__ import annotations

import ipaddress
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

PROJECT_ROOT = Path(settings.BASE_DIR)
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
NS_EXEC = SCRIPTS_DIR / "ns_exec.py"
LAB_NODES = ["a", "r1", "r2", "r3", "b", "c"]
LAB_SCRIPTS = {
    "setup_network.sh", "cleanup_network.sh", "verify_network.sh",
    "simulate_failure.sh", "restore_network.sh", "impair_link.sh",
}
# Interpreter used for privileged helpers. Must match the sudoers entry.
PRIV_PYTHON = os.environ.get("AEGISNET_PRIV_PYTHON", sys.executable)
FORCE_SIM = os.environ.get("AEGISNET_FORCE_SIM") == "1"


class PrivilegeError(RuntimeError):
    pass


@dataclass
class CmdResult:
    argv: list
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.error

    @property
    def text(self) -> str:
        return (self.stdout or "") + (("\n" + self.stderr) if self.stderr.strip() else "")


def ns_of(node: str) -> str:
    return f"aegis_{node}"


def lab_ip_allowed(address: str) -> bool:
    """True when the address lies inside the configured lab networks."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(n) for n in settings.LAB_ALLOWED_NETWORKS)


def _priv_prefix():
    if os.geteuid() == 0:
        return []
    if shutil.which("sudo"):
        return ["sudo", "-n"]
    return None


def build_cmd(node, argv, privileged=None):
    """Return the full command line to run argv on `node` ('host'/None or a lab node)."""
    if node in (None, "", "host"):
        base = [PRIV_PYTHON, "-I", str(NS_EXEC), "--host", "--", *argv]
        need = bool(argv) and argv[0] == "tcpdump"
    else:
        if node not in LAB_NODES:
            raise ValueError(f"unknown lab node {node!r}")
        base = [PRIV_PYTHON, "-I", str(NS_EXEC), "--node", ns_of(node), "--", *argv]
        need = True
    if privileged is not None:
        need = privileged
    if need:
        prefix = _priv_prefix()
        if prefix is None:
            raise PrivilegeError("root or sudo is required for this operation")
        base = prefix + base
    return base


def run(cmd, timeout=15) -> CmdResult:
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return CmdResult(cmd, p.returncode, p.stdout, p.stderr, (time.monotonic() - t0) * 1000)
    except subprocess.TimeoutExpired:
        return CmdResult(cmd, 124, duration_ms=(time.monotonic() - t0) * 1000, error=f"timed out after {timeout}s")
    except FileNotFoundError as exc:
        return CmdResult(cmd, 127, error=f"command not found: {exc.filename}")
    except OSError as exc:
        return CmdResult(cmd, 126, error=str(exc))


def run_in_node(node, argv, timeout=15, privileged=None) -> CmdResult:
    try:
        cmd = build_cmd(node, argv, privileged)
    except (PrivilegeError, ValueError) as exc:
        return CmdResult(list(argv), 126, error=str(exc))
    return run(cmd, timeout=timeout)


def popen_in_node(node, argv, stdout=None, stderr=None, privileged=None) -> subprocess.Popen:
    cmd = build_cmd(node, argv, privileged)
    return subprocess.Popen(cmd, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, start_new_session=True)


def run_script(name: str, *args: str, timeout=60) -> CmdResult:
    """Run one of the lab scripts (root needed unless --dry-run)."""
    if name not in LAB_SCRIPTS:
        return CmdResult([name], 126, error=f"script not allowed: {name}")
    path = str(SCRIPTS_DIR / name)
    cmd = [path, *args]
    if "--dry-run" not in args:
        prefix = _priv_prefix()
        if prefix is None:
            return CmdResult(cmd, 126, error="root or sudo is required")
        cmd = prefix + cmd
    return run(cmd, timeout=timeout)


# --------------------------------------------------------------------------- lab status
_status_cache = {"t": 0.0, "value": None}
_status_lock = threading.Lock()


def _ip_binary():
    return shutil.which("ip") or "/usr/sbin/ip"


def _can_exec_privileged() -> bool:
    if os.geteuid() == 0:
        return True
    if not shutil.which("sudo"):
        return False
    r = run(["sudo", "-n", PRIV_PYTHON, "-I", str(NS_EXEC), "--check"], timeout=5)
    return r.ok


def lab_status(force: bool = False) -> dict:
    """Is the live namespace lab usable? Cached for two seconds."""
    with _status_lock:
        now = time.monotonic()
        if not force and _status_cache["value"] and now - _status_cache["t"] < 2:
            return _status_cache["value"]
        present = []
        r = run([_ip_binary(), "netns", "list"], timeout=5)
        names = {ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()}
        present = [n for n in LAB_NODES if ns_of(n) in names]
        missing = [n for n in LAB_NODES if n not in present]
        privileged = _can_exec_privileged() if not missing else False
        if FORCE_SIM:
            live, reason = False, ""#simulation forced by AEGISNET_FORCE_SIM=1
        elif missing:
            live, reason = False, ("")#lab network not set up (missing namespaces: " + ", ".join(missing) + "). Run scripts/setup_network.sh
        elif not privileged:
            live, reason = False, ""#namespaces exist but this user cannot run the privileged helper (see scripts/print_sudoers.sh)
        else:
            live, reason = True, ""#isolated namespace lab is running
        value = {"live": live, "mode": "live" if live else "simulated", "namespaces": present,
                 "missing": missing, "privileged": privileged, "reason": reason}
        _status_cache.update(t=now, value=value)
        return value


def is_live() -> bool:
    return lab_status()["live"]


def invalidate_status_cache():
    _status_cache["t"] = 0.0
