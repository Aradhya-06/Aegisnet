"""python manage.py collect_ml_data [--samples 40] [--skip-shaping]"""
from django.core.management.base import BaseCommand, CommandError

from ml_extension import collect


class Command(BaseCommand):
    help = "Collect a labelled congestion dataset from the live lab (appends to data/ml/dataset.csv)."

    def add_arguments(self, parser):
        parser.add_argument("--samples", type=int, default=40, help="samples per load level")
        parser.add_argument("--skip-shaping", action="store_true",
                            help="PIPELINE TEST ONLY: do not shape the link (labels would not reflect real congestion)")

    def handle(self, *a, **o):
        try:
            n = collect.collect(o["samples"], o["skip_shaping"], log=self.stdout.write)
        except collect.CollectError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"{n} labelled samples appended to {collect.dataset_path()}"))
