"""Run NS2 scenarios (Tcl scripts in simulation/tcl) and store parsed results.

Honesty rules: if the `ns` binary is missing, the run is recorded as
"not_available" with no numbers. Metrics exist only for runs that really executed.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from django.conf import settings

from .models import SimulationRun
from .trace_parser import parse_trace_file

TCL_DIR = Path(__file__).resolve().parent / "tcl"
RUN_ROOT = settings.DATA_DIR / "ns2"

SCENARIOS = {
    "normal": {"title": "A - Normal network", "file": "scenario_normal.tcl",
               "description": "TCP A to B on the 2 Mb/s primary path plus a light UDP stream A to C. No faults."},
    "congestion": {"title": "B - Congestion", "file": "scenario_congestion.tcl",
                   "description": "A 1.6 Mb/s UDP stream shares the primary link with TCP, a small queue overflows, and at t=6 s the link bandwidth drops to 1.5 Mb/s."},
    "failed_link": {"title": "C - Failed link", "file": "scenario_failed_link.tcl",
                    "description": "Primary link R1-R2 fails at t=4 s and returns at t=8 s. Distance-vector routing moves TCP to the backup path via R3."},
    "lossy_link": {"title": "D - Packet drops", "file": "scenario_lossy_link.tcl",
                   "description": "A 3 % random error model drops packets on the primary link."},
}
FLOW_LABELS = {1: "TCP  PC A -> PC B", 2: "UDP  PC A -> PC C", 3: "UDP  PC A -> PC B (background)"}


def ns_binary():
    return shutil.which("ns")


def script_text(key: str) -> str:
    return (TCL_DIR / SCENARIOS[key]["file"]).read_text()


def run_scenario(key: str, timeout: int = 180) -> SimulationRun:
    if key not in SCENARIOS:
        raise KeyError(key)
    run = SimulationRun.objects.create(scenario=key)
    ns = ns_binary()
    if not ns:
        run.status = "not_available"
        run.log_tail = "NS2 ('ns') is not installed, so nothing was simulated. Install it with: sudo apt install ns2"
        run.save()
        return run
    run.ns_path = ns
    run_dir = RUN_ROOT / f"run_{run.pk}"
    run_dir.mkdir(parents=True, exist_ok=True)
    script = TCL_DIR / SCENARIOS[key]["file"]
    t0 = time.monotonic()
    try:
        proc = subprocess.run([ns, str(script)], cwd=run_dir, capture_output=True, text=True, timeout=timeout)
        run.return_code = proc.returncode
        run.log_tail = ((proc.stdout or "") + (proc.stderr or ""))[-1500:]
    except subprocess.TimeoutExpired:
        run.status, run.log_tail = "failed", f"NS2 did not finish within {timeout}s"
        run.duration_s = round(time.monotonic() - t0, 2)
        run.save()
        return run
    except OSError as exc:
        run.status, run.log_tail = "failed", f"could not start ns: {exc}"
        run.save()
        return run
    run.duration_s = round(time.monotonic() - t0, 2)
    trace = run_dir / "out.tr"
    if run.return_code != 0 or not trace.exists() or trace.stat().st_size == 0:
        run.status = "failed"
        run.save()
        return run
    run.trace_path = str(trace)
    try:
        run.metrics = parse_trace_file(trace, FLOW_LABELS)
    except (ValueError, OSError) as exc:
        run.status, run.log_tail = "failed", f"trace could not be parsed: {exc}"
        run.save()
        return run
    run.status, run.executed = "completed", True
    run.save()
    return run


def latest_by_scenario() -> dict:
    out = {}
    for key in SCENARIOS:
        out[key] = SimulationRun.objects.filter(scenario=key, executed=True).first()
    return out
