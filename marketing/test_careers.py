from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department
from candidates.applications import MAX_PER_EMAIL_PER_HOUR, MAX_PER_IP_PER_HOUR
from candidates.models import Application, Candidate, CandidateInvite, PendingApplication
from cv_screening.models import CandidateCV
from positions.models import Position

PASSWORD = "careers-pass-12345"


def a_cv(name="cv.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 python engineer", content_type="application/pdf")


def form_data(**overrides):
    data = {
        "first_name": "Ada",
        "last_name": "Kore",
        "email": "ada@example.com",
        "phone": "0700999888",
        "message": "I build APIs.",
        "accept_terms": "on",
        "cv_file": a_cv(),
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class CareersPagesTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Engineering")
        self.open_position = Position.objects.create(
            title="Backend Engineer", description="Builds APIs", department=self.department, is_open=True
        )
        self.closed_position = Position.objects.create(
            title="Secret Role", description="Not hiring", department=self.department, is_open=False
        )

    def test_listing_is_public_and_hides_closed_roles(self):
        response = self.client.get(reverse("careers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Backend Engineer")
        self.assertNotContains(response, "Secret Role")

    def test_closed_role_pages_are_not_reachable(self):
        for name in ("careers-detail", "careers-apply"):
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=[self.closed_position.pk]))
                self.assertEqual(response.status_code, 404)

    def test_search_filters_the_listing(self):
        response = self.client.get(reverse("careers"), {"q": "nothing-matches-this"})
        self.assertNotContains(response, "Backend Engineer")

    def test_apply_page_renders_for_an_open_role(self):
        response = self.client.get(reverse("careers-apply", args=[self.open_position.pk]))
        self.assertContains(response, "Apply for Backend Engineer")


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ApplySubmissionTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Engineering")
        self.position = Position.objects.create(
            title="Backend Engineer", description="Builds APIs", department=self.department, is_open=True
        )
        self.url = reverse("careers-apply", args=[self.position.pk])
        patcher = mock.patch("candidates.applications.publish_event", return_value=True)
        self.publish_event = patcher.start()
        self.addCleanup(patcher.stop)

    def test_valid_submission_creates_nothing_in_the_pipeline(self):
        response = self.client.post(self.url, form_data())
        self.assertContains(response, "Check your email")

        self.assertEqual(PendingApplication.objects.count(), 1)
        self.assertFalse(Candidate.objects.exists())
        self.assertFalse(Application.objects.exists())
        self.assertFalse(CandidateCV.objects.exists())

    def test_confirmation_email_carries_the_token(self):
        self.client.post(self.url, form_data())
        pending = PendingApplication.objects.get()
        context = self.publish_event.call_args.kwargs["context"]
        self.assertIn(pending.token, context["confirm_url"])

    def test_missing_fields_are_reported_and_nothing_is_stored(self):
        cases = {
            "first_name": form_data(first_name=""),
            "email": form_data(email="not-an-email"),
            "accept_terms": form_data(accept_terms=None),
        }
        for field, data in cases.items():
            with self.subTest(field=field):
                response = self.client.post(self.url, data)
                self.assertEqual(response.status_code, 200)
        self.assertFalse(PendingApplication.objects.exists())

    def test_a_cv_is_required_and_must_be_the_right_type(self):
        response = self.client.post(self.url, form_data(cv_file=None))
        self.assertContains(response, "Please select a CV file")

        wrong = SimpleUploadedFile("cv.txt", b"hello", content_type="text/plain")
        response = self.client.post(self.url, form_data(cv_file=wrong))
        self.assertContains(response, "Unsupported file type")
        self.assertFalse(PendingApplication.objects.exists())

    def test_the_form_does_not_reveal_whether_an_email_is_known(self):
        Candidate.objects.create(
            first_name="Ada", last_name="Kore", email="ada@example.com", phone="1"
        )
        known = self.client.post(self.url, form_data())
        unknown = self.client.post(self.url, form_data(email="stranger@example.com"))
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertContains(known, "Check your email")
        self.assertContains(unknown, "Check your email")

    def test_repeated_submissions_from_one_address_are_limited(self):
        for _ in range(MAX_PER_EMAIL_PER_HOUR):
            self.client.post(self.url, form_data())
        response = self.client.post(self.url, form_data())
        self.assertContains(response, "wait an hour")
        self.assertEqual(PendingApplication.objects.count(), MAX_PER_EMAIL_PER_HOUR)

    def test_repeated_submissions_from_one_address_block_other_emails_too(self):
        for index in range(MAX_PER_IP_PER_HOUR):
            self.client.post(self.url, form_data(email=f"person{index}@example.com"))
        response = self.client.post(self.url, form_data(email="one-more@example.com"))
        self.assertContains(response, "wait an hour")


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ConfirmApplicationTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Engineering")
        self.position = Position.objects.create(
            title="Backend Engineer", description="Builds APIs", department=self.department, is_open=True
        )
        patcher = mock.patch("candidates.applications.publish_event", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def apply(self, **overrides):
        self.client.post(reverse("careers-apply", args=[self.position.pk]), form_data(**overrides))
        return PendingApplication.objects.latest("created_at")

    def confirm(self, pending):
        return self.client.get(reverse("application-confirm", args=[pending.token]))

    def test_confirming_creates_the_candidate_application_and_cv(self):
        pending = self.apply()
        response = self.confirm(pending)

        candidate = Candidate.objects.get()
        application = Application.objects.get()
        self.assertEqual(candidate.email, "ada@example.com")
        self.assertEqual(candidate.source, "public")
        self.assertIsNotNone(candidate.terms_accepted_at)
        self.assertEqual(application.position, self.position)
        self.assertEqual(application.status, "CV Screening")
        self.assertTrue(CandidateCV.objects.filter(candidate=candidate).exists())

        invite = CandidateInvite.objects.get(candidate=candidate)
        self.assertRedirects(
            response, reverse("portal:accept-invite", args=[invite.token]), fetch_redirect_response=False
        )

    def test_the_applicants_message_reaches_the_recruiter(self):
        pending = self.apply()
        self.confirm(pending)

        application = Application.objects.get()
        self.assertEqual(application.applicant_message, "I build APIs.")

        staff = User.objects.create_superuser("recruiter_msg", "r@example.com", PASSWORD)
        self.client.force_login(staff)
        response = self.client.get(reverse("application-detail", args=[application.pk]))
        self.assertContains(response, "I build APIs.")

    def test_the_ip_address_is_erased_once_confirmed(self):
        pending = self.apply()
        self.confirm(pending)
        pending.refresh_from_db()
        self.assertIsNone(pending.ip_address)
        self.assertIsNotNone(pending.verified_at)

    def test_confirming_attaches_to_an_existing_candidate_record(self):
        existing = Candidate.objects.create(
            first_name="Ada", last_name="Kore", email="ada@example.com", phone=""
        )
        pending = self.apply()
        self.confirm(pending)

        self.assertEqual(Candidate.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.applications.count(), 1)
        self.assertEqual(existing.phone, "0700999888")
        # A staff-entered record keeps its origin.
        self.assertEqual(existing.source, "staff")

    def test_a_second_application_for_the_same_open_role_is_not_created(self):
        first = self.apply()
        self.confirm(first)
        second = self.apply()
        self.confirm(second)

        self.assertEqual(Application.objects.count(), 1)

    def test_applying_again_after_a_closed_application_works(self):
        first = self.apply()
        self.confirm(first)
        Application.objects.update(status="Rejected")

        second = self.apply()
        self.confirm(second)
        self.assertEqual(Application.objects.count(), 2)

    def test_a_used_link_stops_working(self):
        pending = self.apply()
        self.confirm(pending)
        self.assertEqual(self.confirm(pending).status_code, 404)

    def test_expired_and_unknown_links_look_the_same(self):
        pending = self.apply()
        pending.expires_at = timezone.now() - timedelta(minutes=1)
        pending.save(update_fields=["expires_at"])
        self.assertEqual(self.confirm(pending).status_code, 404)
        self.assertEqual(self.client.get(reverse("application-confirm", args=["nope"])).status_code, 404)

    def test_an_existing_account_is_sent_to_sign_in_rather_than_set_a_password(self):
        candidate = Candidate.objects.create(
            first_name="Ada", last_name="Kore", email="ada@example.com", phone="1"
        )
        user = User.objects.create_user("ada@example.com", email="ada@example.com", password=PASSWORD)
        candidate.user = user
        candidate.save(update_fields=["user"])

        pending = self.apply()
        response = self.confirm(pending)
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertFalse(CandidateInvite.objects.exists())


class LoginDoorTests(TestCase):
    """Two sign-in pages, one accounts system: each refuses the other's users."""

    def setUp(self):
        self.candidate_user = User.objects.create_user(
            "ada@example.com", email="ada@example.com", password=PASSWORD
        )
        Candidate.objects.create(
            first_name="Ada", last_name="Kore", email="ada@example.com", phone="1", user=self.candidate_user
        )
        self.staff_user = User.objects.create_user("recruiter9", password=PASSWORD)
        self.staff_user.groups.add(Group.objects.get_or_create(name="Recruiter")[0])

    def test_candidate_is_refused_at_the_staff_door(self):
        response = self.client.post(
            reverse("login"), {"username": "ada@example.com", "password": PASSWORD}
        )
        self.assertContains(response, "candidate portal")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_are_refused_at_the_candidate_door(self):
        response = self.client.post(
            reverse("portal:login"), {"username": "recruiter9", "password": PASSWORD}
        )
        self.assertContains(response, "staff sign-in page")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_each_door_accepts_its_own_users(self):
        self.assertEqual(
            self.client.post(reverse("portal:login"), {"username": "ada@example.com", "password": PASSWORD}).status_code,
            302,
        )
        self.client.logout()
        self.assertEqual(
            self.client.post(reverse("login"), {"username": "recruiter9", "password": PASSWORD}).status_code,
            302,
        )

    def test_an_account_with_no_candidate_record_is_refused_at_the_candidate_door(self):
        User.objects.create_user("stranger", password=PASSWORD)
        response = self.client.post(
            reverse("portal:login"), {"username": "stranger", "password": PASSWORD}
        )
        self.assertContains(response, "linked to an application")
