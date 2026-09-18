"""Deletes public applications nobody ever confirmed.

The privacy notice says an unconfirmed application, and the CV attached to it,
is deleted within 30 days. Nothing enforces that on its own, so this command
is what has to run on a schedule (cron, an Elastic Beanstalk periodic task, or
an EventBridge rule):

    python manage.py purge_pending_applications

It only ever touches PendingApplication rows that were never confirmed, and
whose link has already expired. Confirmed applications are real candidate
records by then and are never touched here.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from candidates.applications import expired_pending_queryset, purge_expired_pending

DEFAULT_DAYS = 30


class Command(BaseCommand):
    help = "Delete unconfirmed public applications (and their CVs) older than the retention period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_DAYS,
            help=f"How long after expiry to keep them. Default {DEFAULT_DAYS}, matching the privacy notice.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted, delete nothing.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        due = expired_pending_queryset(days)
        count = due.count()

        if options["dry_run"]:
            self.stdout.write(f"{count} unconfirmed application(s) would be deleted (older than {days} days).")
            for pending in due[:20]:
                self.stdout.write(f"  {pending.created_at:%Y-%m-%d}  {pending.position.title}")
            return

        deleted = purge_expired_pending(days)
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} unconfirmed application(s) and their CVs "
                f"at {timezone.now():%Y-%m-%d %H:%M}."
            )
        )
