from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import audit
from accounts.models import AuditEvent

PASSWORD = "audit-test-pw-77120"


class AuditRecordingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("audit_user", password=PASSWORD)
        self.user.groups.add(Group.objects.get_or_create(name="Recruiter")[0])

    def test_a_successful_sign_in_is_recorded_with_the_address(self):
        self.client.post(reverse("login"), {"username": "audit_user", "password": PASSWORD})

        event = AuditEvent.objects.get(action=audit.LOGIN)
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.actor_label, "audit_user")
        self.assertTrue(event.ip_address, "sign-in events need the address they came from")

    def test_a_failed_sign_in_records_the_attempted_username(self):
        self.client.post(reverse("login"), {"username": "audit_user", "password": "wrong"})

        event = AuditEvent.objects.get(action=audit.LOGIN_FAILED)
        self.assertEqual(event.detail["attempted_username"], "audit_user")
        self.assertIsNone(event.actor, "a failed attempt has no authenticated actor")

    def test_a_failed_sign_in_never_records_the_password(self):
        self.client.post(reverse("login"), {"username": "audit_user", "password": "hunter2-secret"})
        for event in AuditEvent.objects.all():
            self.assertNotIn("hunter2-secret", str(event.detail))

    def test_signing_out_is_recorded(self):
        self.client.force_login(self.user)
        self.client.post(reverse("logout"))
        self.assertTrue(AuditEvent.objects.filter(action=audit.LOGOUT, actor=self.user).exists())

    def test_entries_cannot_be_edited(self):
        """An audit log an administrator can rewrite proves nothing."""
        event = audit.record(audit.LOGIN, actor=self.user)
        event.action = audit.CANDIDATE_DELETED

        with self.assertRaises(ValueError):
            event.save()

    def test_labels_survive_the_actor_being_deleted(self):
        audit.record(audit.CANDIDATE_DELETED, actor=self.user, deleted_name="Someone")
        self.user.delete()

        event = AuditEvent.objects.get(action=audit.CANDIDATE_DELETED)
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, "audit_user", "the entry must still say who did it")

    def test_a_broken_audit_write_never_breaks_the_action(self):
        from unittest import mock

        with mock.patch("accounts.models.AuditEvent.objects.create", side_effect=Exception("table gone")):
            self.assertIsNone(audit.record(audit.LOGIN, actor=self.user))

    def test_device_details_are_only_kept_for_authentication(self):
        request_ip = "203.0.113.9"
        from django.test import RequestFactory

        request = RequestFactory().get("/", REMOTE_ADDR=request_ip, HTTP_USER_AGENT="probe/1.0")
        request.user = self.user

        audit.record(audit.LOGIN, request=request)
        audit.record(audit.CANDIDATE_UPDATED, request=request)

        self.assertEqual(AuditEvent.objects.get(action=audit.LOGIN).ip_address, request_ip)
        self.assertIsNone(AuditEvent.objects.get(action=audit.CANDIDATE_UPDATED).ip_address)


class AuditAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        audit.record(audit.LOGIN, actor_label="someone")

    def sign_in_as(self, username, group=None, superuser=False):
        user = (
            User.objects.create_superuser(username, f"{username}@example.com", PASSWORD)
            if superuser
            else User.objects.create_user(username, password=PASSWORD)
        )
        if group:
            user.groups.add(Group.objects.get_or_create(name=group)[0])
        self.client.force_login(user)
        return user

    def test_a_recruiter_cannot_read_the_audit_log(self):
        self.sign_in_as("plain_recruiter", group="Recruiter")
        self.assertEqual(self.client.get(reverse("audit-log")).status_code, 403)

    def test_an_interviewer_cannot_read_the_audit_log(self):
        self.sign_in_as("plain_interviewer", group="HR Interviewer")
        self.assertEqual(self.client.get(reverse("audit-log")).status_code, 403)

    def test_leadership_can_read_it(self):
        self.sign_in_as("leader", group="Leadership Manager")
        self.assertEqual(self.client.get(reverse("audit-log")).status_code, 200)

    def test_an_administrator_can_read_it(self):
        self.sign_in_as("admin_person", group="Administrator")
        self.assertEqual(self.client.get(reverse("audit-log")).status_code, 200)

    def test_anonymous_visitors_are_sent_to_sign_in(self):
        response = self.client.get(reverse("audit-log"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])


class AuditRetentionTests(TestCase):
    def test_only_entries_past_the_retention_period_are_removed(self):
        recent = audit.record(audit.LOGIN, actor_label="recent")
        old = audit.record(audit.LOGIN, actor_label="old")
        AuditEvent.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=audit.AUDIT_RETENTION_DAYS + 1)
        )

        out = StringIO()
        call_command("purge_audit_events", stdout=out)

        self.assertTrue(AuditEvent.objects.filter(pk=recent.pk).exists())
        self.assertFalse(AuditEvent.objects.filter(pk=old.pk).exists())

    def test_dry_run_reports_without_deleting(self):
        old = audit.record(audit.LOGIN, actor_label="old")
        AuditEvent.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=audit.AUDIT_RETENTION_DAYS + 1)
        )

        out = StringIO()
        call_command("purge_audit_events", "--dry-run", stdout=out)

        self.assertIn("would be deleted", out.getvalue())
        self.assertTrue(AuditEvent.objects.filter(pk=old.pk).exists())
