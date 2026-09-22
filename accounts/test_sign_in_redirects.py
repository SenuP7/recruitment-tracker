"""Signed out is a different answer from not allowed.

Every staff page must send a signed-out visitor to sign in, and keep a 403
for signed-in users whose role doesn't include the page. The candidate,
application, position and interview views used to answer both with a bare
403, because PermissionRequiredMixin(raise_exception=True) applies to
anonymous visitors too. The Playwright QA suite found it (2026-09-22).
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

STAFF_PAGES = [
    "candidate-list",
    "candidate-create",
    "application-list",
    "position-list",
    "position-create",
    "interview-list",
    "my-interviews",
]


class SignedOutVisitorTests(TestCase):
    def test_every_staff_page_redirects_to_sign_in_with_a_way_back(self):
        for name in STAFF_PAGES:
            with self.subTest(page=name):
                path = reverse(name)
                response = self.client.get(path)

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, f"{reverse('login')}?next={path}")


class SignedInWithoutPermissionTests(TestCase):
    def setUp(self):
        # Signed in, but in no group and holding no permissions.
        self.user = User.objects.create_user("no_role_check", password="pass12345")
        self.client.login(username="no_role_check", password="pass12345")

    def test_the_refusal_is_still_a_403(self):
        for name in STAFF_PAGES:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_the_403_explains_itself_instead_of_the_django_default(self):
        response = self.client.get(reverse("candidate-list"))

        self.assertEqual(response.status_code, 403)
        body = response.content.decode()
        self.assertIn("You don't have access to this page.", body)
        self.assertIn("ask an administrator", body)
