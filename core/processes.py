"""Start / stop helper processes (test servers, fault detector) and remember them."""
from __future__ import annotations

import os
import signal
import sys
import time

from django.conf import settings
from django.utils import timezone

from .models import ManagedProcess
from .netenv import PRIV_PYTHON, popen_in_node, PROJECT_ROOT

RUN_DIR = settings.DATA_DIR / "run"


def _alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by root (sudo'd helper)
    # reap zombies of our own children
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except ChildProcessError:
        pass
    return True


def refresh(proc: ManagedProcess) -> ManagedProcess:
    if proc.status == ManagedProcess.RUNNING and not _alive(proc.pid):
        proc.status = ManagedProcess.STOPPED
        proc.save(update_fields=["status"])
    return proc


def is_running(name: str) -> bool:
    proc = ManagedProcess.objects.filter(name=name).first()
    return bool(proc and refresh(proc).status == ManagedProcess.RUNNING)


def start_service(name: str, kind: str, node: str, argv: list[str]) -> ManagedProcess:
    """Start `python -m <module> ...` on a lab node (or the host when node == 'host')."""
    existing = ManagedProcess.objects.filter(name=name).first()
    if existing and refresh(existing).status == ManagedProcess.RUNNING:
        return existing
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUN_DIR / f"{name}.log"
    logf = open(log_path, "ab")
    # python3 is rewritten to the validated interpreter by scripts/ns_exec.py
    proc = popen_in_node(node, ["python3", "-m", *argv], stdout=logf, stderr=logf)
    time.sleep(0.4)
    ok = proc.poll() is None
    obj, _ = ManagedProcess.objects.update_or_create(
        name=name,
        defaults=dict(kind=kind, node=node, command=" ".join(argv), pid=proc.pid,
                      status=ManagedProcess.RUNNING if ok else ManagedProcess.STOPPED,
                      expected_up=ok, started_at=timezone.now(), log_path=str(log_path)),
    )
    return obj


def start_manage_command(name: str, kind: str, args: list[str]) -> ManagedProcess:
    """Start `python manage.py <args>` on the host (used for the fault detector)."""
    existing = ManagedProcess.objects.filter(name=name).first()
    if existing and refresh(existing).status == ManagedProcess.RUNNING:
        return existing
    import subprocess
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUN_DIR / f"{name}.log"
    logf = open(log_path, "ab")
    proc = subprocess.Popen([sys.executable, str(PROJECT_ROOT / "manage.py"), *args], stdout=logf, stderr=logf,
                            stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(PROJECT_ROOT))
    time.sleep(0.6)
    obj, _ = ManagedProcess.objects.update_or_create(
        name=name,
        defaults=dict(kind=kind, node="host", command="manage.py " + " ".join(args), pid=proc.pid,
                      status=ManagedProcess.RUNNING if proc.poll() is None else ManagedProcess.STOPPED,
                      expected_up=proc.poll() is None, started_at=timezone.now(), log_path=str(log_path)),
    )
    return obj


def stop(name: str) -> bool:
    proc = ManagedProcess.objects.filter(name=name).first()
    if not proc:
        return False
    if proc.pid and _alive(proc.pid):
        try:
            os.kill(proc.pid, signal.SIGTERM)  # sudo relays SIGTERM to the real server
        except (ProcessLookupError, PermissionError):
            pass
        for _ in range(20):
            if not _alive(proc.pid):
                break
            time.sleep(0.1)
    proc.status = ManagedProcess.STOPPED
    proc.expected_up = False          # deliberate stop: not a fault
    proc.save(update_fields=["status", "expected_up"])
    return True


def crash(name: str) -> bool:
    """Failure injection: kill the process but keep expected_up=True so the detector sees a fault."""
    proc = ManagedProcess.objects.filter(name=name).first()
    if not proc or not proc.pid or not _alive(proc.pid):
        return False
    try:
        os.kill(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    for _ in range(20):
        if not _alive(proc.pid):
            break
        time.sleep(0.1)
    proc.status = ManagedProcess.STOPPED
    proc.save(update_fields=["status"])
    return True


def stop_all():
    for proc in ManagedProcess.objects.all():
        stop(proc.name)
