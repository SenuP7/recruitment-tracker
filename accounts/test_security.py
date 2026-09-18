"""Security behaviour that must not regress.

These are deliberately behavioural: they sign in, they upload, they try to
reach another candidate's data, rather than asserting that a setting has a
particular value.
"""

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import throttling
from accounts.models import Department
from candidates.models import Application, Candidate
from cv_screening.models import CandidateCV
from cv_screening.uploads import validate_cv_file
from positions.models import Position

PASSWORD = "security-test-pw-8842"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class LoginThrottlingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("throttle_target", password=PASSWORD)
        self.user.groups.add(Group.objects.get_or_create(name="Recruiter")[0])

    def attempt(self, password):
        return self.client.post(
            reverse("login"), {"username": "throttle_target", "password": password}
        )

    def test_repeated_wrong_passwords_lock_the_account_out(self):
        for _ in range(throttling.LOGIN_MAX_PER_USERNAME):
            self.attempt("wrong-password")

        response = self.attempt("wrong-password")
        self.assertContains(response, "Too many attempts")

    def test_a_locked_out_attacker_cannot_get_in_with_the_right_password(self):
        """The lockout has to apply before the password is checked, or it's
        only a speed bump."""
        for _ in range(throttling.LOGIN_MAX_PER_USERNAME):
            self.attempt("wrong-password")

        response = self.attempt(PASSWORD)
        self.assertContains(response, "Too many attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_successful_sign_in_clears_the_count(self):
        for _ in range(throttling.LOGIN_MAX_PER_USERNAME - 1):
            self.attempt("wrong-password")

        self.assertEqual(self.attempt(PASSWORD).status_code, 302)
        self.client.logout()
        self.assertEqual(self.attempt(PASSWORD).status_code, 302)

    def test_lockout_says_nothing_about_whether_the_account_exists(self):
        for _ in range(throttling.LOGIN_MAX_PER_USERNAME):
            self.client.post(reverse("login"), {"username": "no-such-person", "password": "x"})
        real = self.client.post(reverse("login"), {"username": "no-such-person", "password": "x"})
        self.assertContains(real, "Too many attempts")

    def test_password_reset_requests_are_capped_per_address(self):
        for _ in range(throttling.RESET_MAX_PER_IP + 2):
            response = self.client.post(reverse("password_reset"), {"email": "someone@example.com"})
        # Still the same confirmation page: throttling must not become a way
        # to find out which addresses are registered.
        self.assertEqual(response.status_code, 302)
        self.assertTrue(throttling.reset_requests_exhausted(_request_with_ip()))


def _request_with_ip():
    from django.test import RequestFactory

    return RequestFactory().get("/", REMOTE_ADDR="127.0.0.1")


@override_settings(STORAGES=STORAGES)
class CandidateDataIsolationTests(TestCase):
    """One candidate must not be able to read or change another's data, by
    any route: page, file download, or POST."""

    def setUp(self):
        cache.clear()
        department = Department.objects.create(name="Engineering")
        self.position = Position.objects.create(
            title="Backend Engineer", description="APIs", department=department, is_open=True
        )
        self.mine, self.my_app, self.my_cv = self.make_candidate("mine@example.com")
        self.theirs, self.their_app, self.their_cv = self.make_candidate("theirs@example.com")
        self.client.force_login(self.mine.user)

    def make_candidate(self, email):
        candidate = Candidate.objects.create(
            first_name="A", last_name="B", email=email, phone="1"
        )
        user = User.objects.create_user(email, email=email, password=PASSWORD)
        user.groups.add(Group.objects.get_or_create(name="Candidate")[0])
        candidate.user = user
        candidate.save(update_fields=["user"])
        application = Application.objects.create(candidate=candidate, position=self.position)
        cv = CandidateCV.objects.create(
            candidate=candidate,
            file=SimpleUploadedFile(f"{email}.pdf", b"%PDF-1.4 hello", content_type="application/pdf"),
        )
        return candidate, application, cv

    def test_cannot_open_another_candidates_application(self):
        response = self.client.get(
            reverse("portal:application-detail", args=[self.their_app.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_cannot_download_another_candidates_cv(self):
        response = self.client.get(reverse("portal:cv-download", args=[self.their_cv.pk]))
        self.assertEqual(response.status_code, 404)

    def test_can_download_their_own_cv(self):
        response = self.client.get(reverse("portal:cv-download", args=[self.my_cv.pk]))
        self.assertEqual(response.status_code, 200)

    def test_cannot_upload_a_cv_against_another_candidates_application(self):
        response = self.client.post(
            reverse("portal:cv-upload", args=[self.their_app.pk]),
            {"cv_file": SimpleUploadedFile("x.pdf", b"%PDF-1.4 x", content_type="application/pdf")},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(CandidateCV.objects.filter(candidate=self.theirs).count(), 1)

    def test_cannot_withdraw_another_candidates_application(self):
        self.client.post(reverse("portal:withdraw", args=[self.their_app.pk]))
        self.their_app.refresh_from_db()
        self.assertNotEqual(self.their_app.status, "Withdrawn")

    def test_the_staff_cv_download_is_not_reachable_by_a_candidate(self):
        response = self.client.get(
            reverse("cv_screening:view_cv", args=[self.their_cv.pk])
        )
        self.assertIn(response.status_code, (302, 403))

    def test_logging_out_invalidates_the_session(self):
        self.assertIn("_auth_user_id", self.client.session)
        self.client.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.get(reverse("portal:overview"))
        self.assertEqual(response.status_code, 302)


class UploadContentTests(TestCase):
    """Extension checks alone let anything through under a .pdf name."""

    def test_a_file_that_is_not_really_a_pdf_is_rejected(self):
        disguised = SimpleUploadedFile(
            "cv.pdf", b"<?php system($_GET['c']); ?>", content_type="application/pdf"
        )
        self.assertIn("doesn't look like", validate_cv_file(disguised))

    def test_a_real_pdf_and_docx_are_accepted(self):
        self.assertIsNone(
            validate_cv_file(SimpleUploadedFile("cv.pdf", b"%PDF-1.7 real", content_type="application/pdf"))
        )
        self.assertIsNone(
            validate_cv_file(
                SimpleUploadedFile("cv.docx", b"PK\x03\x04 zip container", content_type="application/vnd")
            )
        )

    def test_validation_leaves_the_file_readable(self):
        """Sniffing the first bytes must not consume the upload."""
        upload = SimpleUploadedFile("cv.pdf", b"%PDF-1.7 body text", content_type="application/pdf")
        validate_cv_file(upload)
        self.assertTrue(upload.read().startswith(b"%PDF"))
