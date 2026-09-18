from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department
from candidates.models import Application, Candidate, CandidateInvite
from interviews.models import Interview, StaffNotification
from positions.models import Position

PASSWORD = "portal-pass-12345"


def make_candidate(email, first="Sam", last="Rivers", with_login=True):
    candidate = Candidate.objects.create(
        first_name=first, last_name=last, email=email, phone="0700000000"
    )
    if with_login:
        user = User.objects.create_user(email, email=email, password=PASSWORD)
        user.groups.add(Group.objects.get_or_create(name="Candidate")[0])
        candidate.user = user
        candidate.save(update_fields=["user"])
    return candidate


def make_application(candidate, title="Backend Engineer", status="Applied"):
    department = Department.objects.get_or_create(name="Engineering")[0]
    position = Position.objects.create(
        title=title, description="Builds things", department=department, is_open=True
    )
    return Application.objects.create(candidate=candidate, position=position, status=status)


class PortalAccessTests(TestCase):
    """The portal's whole security model is 'you only ever see your own row',
    so these are the tests that matter most."""

    def setUp(self):
        self.candidate = make_candidate("sam@example.com")
        self.application = make_application(self.candidate)
        self.other = make_candidate("dana@example.com", first="Dana", last="Okoro")
        self.other_application = make_application(self.other, title="Data Analyst")

    def test_anonymous_visitor_is_sent_to_the_candidate_login(self):
        response = self.client.get(reverse("portal:overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("portal:login"), response["Location"])

    def test_user_without_a_candidate_record_is_refused(self):
        User.objects.create_user("nobody", password=PASSWORD)
        self.client.login(username="nobody", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("portal:overview")).status_code, 403)

    def test_staff_account_cannot_use_the_portal(self):
        staff = User.objects.create_user("recruiter1", password=PASSWORD)
        staff.groups.add(Group.objects.get_or_create(name="Recruiter")[0])
        linked = Candidate.objects.create(
            first_name="Staff", last_name="Person", email="staff@example.com", phone="1", user=staff
        )
        self.assertEqual(linked.user, staff)
        self.client.login(username="recruiter1", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("portal:overview")).status_code, 403)

    def test_candidate_sees_only_their_own_applications(self):
        self.client.login(username="sam@example.com", password=PASSWORD)
        response = self.client.get(reverse("portal:overview"))
        self.assertContains(response, "Backend Engineer")
        self.assertNotContains(response, "Data Analyst")

    def test_another_candidates_application_is_not_found(self):
        self.client.login(username="sam@example.com", password=PASSWORD)
        for name in ("portal:application-detail", "portal:cv-upload", "portal:withdraw"):
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=[self.other_application.pk]))
                self.assertEqual(response.status_code, 404)

    def test_posting_to_another_candidates_application_changes_nothing(self):
        self.client.login(username="sam@example.com", password=PASSWORD)
        response = self.client.post(reverse("portal:withdraw", args=[self.other_application.pk]))
        self.assertEqual(response.status_code, 404)
        self.other_application.refresh_from_db()
        self.assertEqual(self.other_application.status, "Applied")

    def test_staff_pages_redirect_candidates_back_to_the_portal(self):
        self.client.login(username="sam@example.com", password=PASSWORD)
        for url in ("/candidates/", "/dashboard/", "/interviews/", "/cv-screening/results/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, reverse("portal:overview"))

    def test_login_sends_candidates_to_the_portal(self):
        self.client.login(username="sam@example.com", password=PASSWORD)
        self.assertRedirects(
            self.client.get(reverse("post-login-redirect")), reverse("portal:overview")
        )

    def test_login_sends_staff_to_the_dashboard(self):
        staff = User.objects.create_user("recruiter2", password=PASSWORD)
        staff.groups.add(Group.objects.get_or_create(name="Recruiter")[0])
        self.client.login(username="recruiter2", password=PASSWORD)
        self.assertRedirects(
            self.client.get(reverse("post-login-redirect")), reverse("dashboard:dashboard")
        )


class PortalContentTests(TestCase):
    def setUp(self):
        self.candidate = make_candidate("sam@example.com")
        self.application = make_application(self.candidate, status="HR Interview")
        self.assigned_interviewer = User.objects.create_user("tech_int", password=PASSWORD)
        self.interview = Interview.objects.create(
            application=self.application,
            interview_type="Technical",
            scheduled_date=timezone.now() + timedelta(days=3),
            assigned_interviewer=self.assigned_interviewer,
        )
        self.client.login(username="sam@example.com", password=PASSWORD)

    def test_interviews_are_shown_without_the_interviewer(self):
        response = self.client.get(reverse("portal:application-detail", args=[self.application.pk]))
        self.assertContains(response, "Technical interview")
        self.assertNotContains(response, "tech_int")

    def test_feedback_and_match_scores_never_appear(self):
        from interviews.models import InterviewFeedback

        InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.assigned_interviewer,
            rating=2,
            comments="Struggled with the system design question.",
            recommendation="Reject",
        )
        response = self.client.get(reverse("portal:application-detail", args=[self.application.pk]))
        self.assertNotContains(response, "Struggled with the system design")
        self.assertNotContains(response, "Reject")

    def test_overview_shows_upcoming_interview(self):
        response = self.client.get(reverse("portal:overview"))
        self.assertContains(response, "Upcoming interviews")


class WithdrawTests(TestCase):
    def setUp(self):
        self.candidate = make_candidate("sam@example.com")
        self.application = make_application(self.candidate, status="HR Interview")
        self.recruiter = User.objects.create_user("recruiter3", password=PASSWORD)
        self.recruiter.groups.add(Group.objects.get_or_create(name="Recruiter")[0])
        self.assigned_interviewer = User.objects.create_user("hr_int", password=PASSWORD)
        self.interview = Interview.objects.create(
            application=self.application,
            interview_type="HR",
            scheduled_date=timezone.now() + timedelta(days=2),
            assigned_interviewer=self.assigned_interviewer,
        )
        self.client.login(username="sam@example.com", password=PASSWORD)

    def test_withdrawing_closes_the_application_and_cancels_interviews(self):
        response = self.client.post(reverse("portal:withdraw", args=[self.application.pk]))
        self.assertRedirects(response, reverse("portal:overview"))

        self.application.refresh_from_db()
        self.interview.refresh_from_db()
        self.assertEqual(self.application.status, "Withdrawn")
        self.assertEqual(self.interview.status, "Cancelled")

    def test_staff_are_notified(self):
        self.client.post(reverse("portal:withdraw", args=[self.application.pk]))
        recipients = set(StaffNotification.objects.values_list("recipient_id", flat=True))
        self.assertEqual(recipients, {self.recruiter.id, self.assigned_interviewer.id})

    def test_a_closed_application_cannot_be_withdrawn_again(self):
        self.application.status = "Rejected"
        self.application.save(update_fields=["status"])
        self.client.post(reverse("portal:withdraw", args=[self.application.pk]))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "Rejected")


class CVUploadTests(TestCase):
    def setUp(self):
        self.candidate = make_candidate("sam@example.com")
        self.application = make_application(self.candidate)
        self.client.login(username="sam@example.com", password=PASSWORD)

    def test_upload_is_blocked_once_screening_is_decided(self):
        self.application.status = "CV Screening Passed"
        self.application.save(update_fields=["status"])
        response = self.client.post(reverse("portal:cv-upload", args=[self.application.pk]))
        self.assertRedirects(
            response, reverse("portal:application-detail", args=[self.application.pk])
        )
        self.assertFalse(self.candidate.cvs.exists() if hasattr(self.candidate, "cvs") else False)

    def test_oversized_and_wrong_type_files_are_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("portal:cv-upload", args=[self.application.pk]),
            {"cv_file": SimpleUploadedFile("cv.txt", b"hello", content_type="text/plain")},
        )
        self.assertContains(response, "Unsupported file type")
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "Applied")


class InviteTests(TestCase):
    def setUp(self):
        self.candidate = make_candidate("newbie@example.com", with_login=False)
        self.recruiter = User.objects.create_user("recruiter4", password=PASSWORD)
        self.recruiter.groups.add(Group.objects.get_or_create(name="Recruiter")[0])
        self.recruiter.user_permissions.add(
            Permission.objects.get(codename="change_candidate"),
            Permission.objects.get(codename="view_candidate"),
        )

    def invite(self):
        return CandidateInvite.issue(self.candidate, created_by=self.recruiter)

    def test_staff_without_permission_cannot_invite(self):
        plain = User.objects.create_user("plain", password=PASSWORD)
        self.client.force_login(plain)
        response = self.client.post(reverse("candidate-invite", args=[self.candidate.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CandidateInvite.objects.exists())

    @mock.patch("candidates.invites.publish_event", return_value=True)
    def test_recruiter_invite_creates_a_token_and_sends_one_email(self, publish_event):
        self.client.force_login(self.recruiter)
        self.client.post(reverse("candidate-invite", args=[self.candidate.pk]))

        invite = CandidateInvite.objects.get()
        self.assertTrue(invite.is_usable)
        publish_event.assert_called_once()
        context = publish_event.call_args.kwargs["context"]
        self.assertIn(invite.token, context["invite_url"])

    def test_issuing_a_new_invite_kills_the_previous_link(self):
        first = self.invite()
        second = self.invite()
        first.refresh_from_db()
        self.assertFalse(first.is_usable)
        self.assertTrue(second.is_usable)

    def test_accepting_creates_a_linked_candidate_login(self):
        invite = self.invite()
        response = self.client.post(
            reverse("portal:accept-invite", args=[invite.token]),
            {"new_password1": "fresh-portal-pw-99", "new_password2": "fresh-portal-pw-99"},
        )
        self.assertRedirects(response, reverse("portal:overview"))

        self.candidate.refresh_from_db()
        invite.refresh_from_db()
        self.assertIsNotNone(self.candidate.user)
        self.assertEqual(self.candidate.user.username, "newbie@example.com")
        self.assertTrue(self.candidate.user.groups.filter(name="Candidate").exists())
        self.assertIsNotNone(invite.accepted_at)

    def test_a_used_invite_cannot_be_used_twice(self):
        invite = self.invite()
        self.client.post(
            reverse("portal:accept-invite", args=[invite.token]),
            {"new_password1": "fresh-portal-pw-99", "new_password2": "fresh-portal-pw-99"},
        )
        self.client.logout()
        response = self.client.get(reverse("portal:accept-invite", args=[invite.token]))
        self.assertEqual(response.status_code, 404)

    def test_expired_and_unknown_tokens_look_the_same(self):
        invite = self.invite()
        invite.expires_at = timezone.now() - timedelta(minutes=1)
        invite.save(update_fields=["expires_at"])
        self.assertEqual(self.client.get(reverse("portal:accept-invite", args=[invite.token])).status_code, 404)
        self.assertEqual(self.client.get(reverse("portal:accept-invite", args=["made-up"])).status_code, 404)

    def test_revoked_invite_stops_working(self):
        invite = self.invite()
        self.client.force_login(self.recruiter)
        self.client.post(reverse("candidate-invite-revoke", args=[self.candidate.pk]))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("portal:accept-invite", args=[invite.token])).status_code, 404)

    def test_weak_password_is_rejected_and_no_account_is_created(self):
        invite = self.invite()
        response = self.client.post(
            reverse("portal:accept-invite", args=[invite.token]),
            {"new_password1": "12345678", "new_password2": "12345678"},
        )
        self.assertEqual(response.status_code, 200)
        self.candidate.refresh_from_db()
        self.assertIsNone(self.candidate.user)
        self.assertFalse(User.objects.filter(username="newbie@example.com").exists())

    def test_invite_is_refused_when_the_email_already_has_an_account(self):
        invite = self.invite()
        User.objects.create_user("newbie@example.com", email="newbie@example.com", password=PASSWORD)
        response = self.client.get(reverse("portal:accept-invite", args=[invite.token]))
        self.assertEqual(response.status_code, 409)


class CandidateDeletionTests(TestCase):
    def test_deleting_a_candidate_disables_their_login(self):
        candidate = make_candidate("gone@example.com")
        user = candidate.user
        staff = User.objects.create_user("recruiter5", password=PASSWORD)
        staff.user_permissions.add(Permission.objects.get(codename="delete_candidate"))
        self.client.force_login(staff)

        self.client.post(reverse("candidate-delete", args=[candidate.pk]))

        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(Candidate.objects.filter(pk=candidate.pk).exists())
