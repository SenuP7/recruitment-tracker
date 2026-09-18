"""Tells you whether outgoing email is actually wired up.

    python manage.py check_notifications
    python manage.py check_notifications --send you@example.com

Applications and password resets both depend on email: with nothing
configured, `publish_event` logs a warning and returns False, so nobody can
finish applying and nobody can reset a password. This reports which of the
three modes you're in, and can put one real message through the pipeline.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from notification_client import event_types
from notification_client.publisher import publish_event


class Command(BaseCommand):
    help = "Report how notification email is configured, and optionally send a test message."

    def add_arguments(self, parser):
        parser.add_argument(
            "--send",
            metavar="EMAIL",
            help="Put one test message through the configured path, addressed here.",
        )

    def handle(self, *args, **options):
        write = self.stdout.write
        local = settings.NOTIFICATIONS_LOCAL_MODE
        queue = settings.NOTIFICATIONS_SQS_QUEUE_URL

        if local:
            mode = "LOCAL"
            write(self.style.WARNING("Mode: local. Emails are written to local_notifications/, not sent."))
        elif queue:
            mode = "LIVE"
            write(self.style.SUCCESS("Mode: live. Events go to the SQS queue for the Lambda to send."))
            write(f"  Region: {settings.NOTIFICATIONS_AWS_REGION}")
        else:
            mode = "OFF"
            write(self.style.ERROR("Mode: off. NOTIFICATIONS_SQS_QUEUE_URL is empty."))
            write("  Nothing is sent, so:")
            write("   - a public applicant never gets the link, so no application is ever confirmed;")
            write("   - a portal invite is created but never delivered;")
            write("   - password resets silently go nowhere.")
            write("  Set NOTIFICATIONS_SQS_QUEUE_URL, or NOTIFICATIONS_LOCAL_MODE=True to test locally.")

        if not options["send"]:
            write("")
            write("Add --send you@example.com to put one test message through it.")
            return

        recipient = options["send"]
        if mode == "LIVE":
            write(self.style.WARNING(f"Sending a real email to {recipient} via SES."))
            write("  In the SES sandbox, the address must be verified or it will bounce.")

        sent = publish_event(
            event_types.PORTAL_INVITE,
            recipient_email=recipient,
            recipient_name="Test recipient",
            context={
                "candidate_name": "Test recipient",
                "company_name": settings.CANDIDFLOW_COMPANY_NAME,
                "invite_url": "https://example.invalid/this-is-a-test",
                "expires_at": "not a real invite",
            },
        )

        if sent:
            write(self.style.SUCCESS("Accepted by the pipeline."))
            if mode == "LOCAL":
                write("  Look in local_notifications/ for the rendered message.")
            else:
                write("  Check the Lambda logs and the DynamoDB audit table for delivery.")
        else:
            write(self.style.ERROR("The publisher refused it. Check credentials, region and the queue URL."))
