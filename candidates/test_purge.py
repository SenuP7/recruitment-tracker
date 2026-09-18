from datetime import timedelta
from io import StringIO

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Department
from candidates.applications import PENDING_RETENTION_DAYS, expired_pending_queryset
from candidates.models import PendingApplication
from positions.models import Position


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class PurgePendingApplicationsTests(TestCase):
    """The privacy notice promises unconfirmed applications are deleted within
    30 days. These check the command that has to keep that promise."""

    def setUp(self):
        department = Department.objects.create(name="Engineering")
        self.position = Position.objects.create(
            title="Backend Engineer", description="Builds APIs", department=department, is_open=True
        )

    def make_pending(self, *, age_days, verified=False):
        pending = PendingApplication.start(
            position=self.position,
            first_name="Ada",
            last_name="Kore",
            email="ada@example.com",
            phone="",
            message="",
            cv=ContentFile(b"cv bytes", name="cv.pdf"),
            ip_address="127.0.0.1",
        )
        expired = timezone.now() - timedelta(days=age_days)
        PendingApplication.objects.filter(pk=pending.pk).update(
            expires_at=expired,
            verified_at=timezone.now() if verified else None,
        )
        return PendingApplication.objects.get(pk=pending.pk)

    def run_command(self, *args):
        out = StringIO()
        call_command("purge_pending_applications", *args, stdout=out)
        return out.getvalue()

    def test_it_deletes_old_unconfirmed_applications_and_their_cvs(self):
        old = self.make_pending(age_days=PENDING_RETENTION_DAYS + 1)
        name = old.cv.name
        storage = old.cv.storage
        self.assertTrue(storage.exists(name))

        self.run_command()

        self.assertFalse(PendingApplication.objects.filter(pk=old.pk).exists())
        self.assertFalse(storage.exists(name), "the CV must go with the record")

    def test_it_leaves_recent_and_confirmed_ones_alone(self):
        recent = self.make_pending(age_days=1)
        confirmed = self.make_pending(age_days=PENDING_RETENTION_DAYS + 5, verified=True)

        self.run_command()

        self.assertTrue(PendingApplication.objects.filter(pk=recent.pk).exists())
        self.assertTrue(PendingApplication.objects.filter(pk=confirmed.pk).exists())

    def test_dry_run_reports_without_deleting(self):
        old = self.make_pending(age_days=PENDING_RETENTION_DAYS + 1)

        output = self.run_command("--dry-run")

        self.assertIn("would be deleted", output)
        self.assertTrue(PendingApplication.objects.filter(pk=old.pk).exists())

    def test_the_retention_period_can_be_shortened(self):
        pending = self.make_pending(age_days=5)
        self.assertEqual(expired_pending_queryset(days=3).count(), 1)
        self.run_command("--days", "3")
        self.assertFalse(PendingApplication.objects.filter(pk=pending.pk).exists())
