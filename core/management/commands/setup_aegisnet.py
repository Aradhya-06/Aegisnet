"""python manage.py setup_aegisnet [--create-user NAME --password PW]

Seeds the lab topology, monitored flows and thresholds. Safe to run repeatedly.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.seed import seed_core


class Command(BaseCommand):
    help = "Seed AegisNet lab topology, flows and thresholds (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--create-user", metavar="USERNAME")
        parser.add_argument("--password", default=None)

    def handle(self, *args, **opts):
        seed_core()
        from recovery.seed import seed_recovery
        seed_recovery()
        self.stdout.write(self.style.SUCCESS("Lab topology, flows and thresholds seeded."))
        username = opts["create_user"]
        if username:
            if not opts["password"]:
                self.stderr.write("--password is required with --create-user")
                return
            User = get_user_model()
            user, created = User.objects.get_or_create(username=username, defaults={"is_staff": True, "is_superuser": True})
            user.set_password(opts["password"])
            user.is_staff = user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"User '{username}' {'created' if created else 'updated'}."))
