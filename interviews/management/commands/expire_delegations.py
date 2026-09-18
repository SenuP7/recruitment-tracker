"""Reverts delegation offers nobody answered in time.

A pending offer 48 hours before the interview is no use: the person who asked
needs to know the round is still theirs. Run this on a schedule alongside the
other housekeeping commands.
"""

from django.core.management.base import BaseCommand

from interviews.delegation import PENDING_EXPIRY_HOURS, expire_stale_offers


class Command(BaseCommand):
    help = "Expire pending interview delegations close to the interview date."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=PENDING_EXPIRY_HOURS)

    def handle(self, *args, **options):
        expired = expire_stale_offers(hours=options["hours"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {expired} pending delegation(s) within {options['hours']} hours of the interview."
            )
        )
