"""Applies the audit log's retention period.

The log is append-only by design, so this command is the only thing that ever
removes an entry. Run it on the same schedule as the other housekeeping.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.audit import AUDIT_RETENTION_DAYS
from accounts.models import AuditEvent
from datetime import timedelta


class Command(BaseCommand):
    help = "Delete audit events older than the retention period."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=AUDIT_RETENTION_DAYS)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        due = AuditEvent.objects.filter(created_at__lt=cutoff)
        count = due.count()

        if options["dry_run"]:
            self.stdout.write(f"{count} audit event(s) older than {options['days']} days would be deleted.")
            return

        due.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} audit event(s) older than {options['days']} days."))
