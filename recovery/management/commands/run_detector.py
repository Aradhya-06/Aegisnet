"""python manage.py run_detector [--interval 5] [--auto-recover] [--dry-run] [--once]

Continuously monitors the lab network and opens/resolves alerts. With --auto-recover
a broken end-to-end path is handed to the recovery engine (in the isolated lab only).
"""
import json
import time

from django.core.management.base import BaseCommand

from recovery import fault_detector


class Command(BaseCommand):
    help = "Run the AegisNet fault detector (optionally with automatic recovery)."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=5.0)
        parser.add_argument("--auto-recover", action="store_true")
        parser.add_argument("--dry-run", action="store_true", help="recovery only prints its plan")
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **o):
        self.stdout.write(f"detector started (interval {o['interval']}s, auto-recover={o['auto_recover']}, dry-run={o['dry_run']})")
        self.stdout.flush()
        try:
            while True:
                try:
                    summary = fault_detector.run_cycle(auto_recover=o["auto_recover"], dry_run=o["dry_run"])
                    self.stdout.write(json.dumps(summary))
                except Exception as exc:          # keep monitoring even if one cycle fails
                    self.stderr.write(f"cycle failed: {exc!r}")
                self.stdout.flush()
                if o["once"]:
                    break
                time.sleep(max(1.0, o["interval"]))
        except KeyboardInterrupt:
            self.stdout.write("detector stopped")
