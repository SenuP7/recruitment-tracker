"""
Regression tests for authentication/logout/session-isolation.

Context: Django 5's LogoutView only accepts POST (http_method_names =
['post', 'options']). Every Logout control in this app used to be a plain
GET <a href> link -- which Django silently rejects with a 405 and does
NOT clear the session. That meant logout never actually happened: the
session just sat there, making the app look permanently stuck on
whichever user logged in first. This predates the dashboard entirely
(present since the initial commit) -- it was never dashboard-specific,
and there is no recruiter01-specific auto-login anywhere in the codebase.

Fix: both Logout controls (templates/base.html, templates/accounts/profile.html)
are now <form method="post"> with {% csrf_token %}, matching Django 5's
requirement. These tests pin that behaviour so it can't silently regress
back to a GET link.
"""

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse


class LogoutRequiresPostTests(TestCase):
    """Documents Django 5's actual LogoutView behaviour, so a Django
    upgrade/downgrade that changes it doesn't go unnoticed."""

    def setUp(self):
        self.user = User.objects.create_user("logout_test_user", password="pass12345")
        self.logout_url = reverse("logout")

    def test_get_logout_does_not_clear_session(self):
        client = Client()
        client.login(username="logout_test_user", password="pass12345")

        response = client.get(self.logout_url)
        self.assertEqual(response.status_code, 405)

        # Session must still be intact -- GET must not have logged anyone out.
        profile_response = client.get(reverse("profile"))
        self.assertEqual(profile_response.status_code, 200)
        self.assertTrue(profile_response.wsgi_request.user.is_authenticated)
        self.assertEqual(
            profile_response.wsgi_request.user.username, "logout_test_user"
        )

    def test_post_logout_clears_session_and_redirects_to_login(self):
        client = Client()
        client.login(username="logout_test_user", password="pass12345")

        response = client.post(self.logout_url)
        self.assertRedirects(response, reverse("login"))

        profile_response = client.get(reverse("profile"))
        self.assertNotEqual(profile_response.status_code, 200)


class LogoutTemplateRegressionTests(TestCase):
    """Pins the actual template fix -- if someone reverts the Logout
    control back to a plain <a href> GET link, this fails immediately
    instead of silently reintroducing the bug."""

    def setUp(self):
        self.user = User.objects.create_user("template_test_user", password="pass12345")
        self.client = Client()
        self.client.login(username="template_test_user", password="pass12345")

    def test_topbar_and_profile_logout_controls_are_post_forms(self):
        # profile/ only requires LoginRequiredMixin (no extra model
        # permission), so this works regardless of the test user's groups,
        # and it renders both the shared topbar's Logout control (every
        # page) and the profile page's own "Actions" Logout button.
        response = self.client.get(reverse("profile"))
        content = response.content.decode()
        self.assertNotIn('href="/accounts/logout/"', content)
        self.assertEqual(content.count('action="/accounts/logout/"'), 2)
        self.assertEqual(content.count('method="post"'), 2)


class SessionIsolationTests(TestCase):
    """Task 13/15: logging out and logging in as a different account must
    fully switch request.user, with no residual permissions from the
    previous session."""

    def setUp(self):
        self.recruiter_group, _ = Group.objects.get_or_create(name="Recruiter")
        self.tech_group, _ = Group.objects.get_or_create(name="Technical Interviewer")

        self.user_a = User.objects.create_user("session_user_a", password="pass12345")
        self.user_a.groups.add(self.recruiter_group)

        self.user_b = User.objects.create_user("session_user_b", password="pass12345")
        self.user_b.groups.add(self.tech_group)

        self.login_url = reverse("login")
        self.logout_url = reverse("logout")

    def test_login_logout_login_as_different_user_switches_identity(self):
        client = Client()

        client.login(username="session_user_a", password="pass12345")
        response = client.get(reverse("profile"))
        self.assertEqual(response.wsgi_request.user.username, "session_user_a")
        self.assertTrue(
            response.wsgi_request.user.groups.filter(name="Recruiter").exists()
        )

        client.post(self.logout_url)
        anon_response = client.get(reverse("profile"))
        self.assertFalse(anon_response.wsgi_request.user.is_authenticated)

        client.login(username="session_user_b", password="pass12345")
        response = client.get(reverse("profile"))
        self.assertEqual(response.wsgi_request.user.username, "session_user_b")
        self.assertNotEqual(response.wsgi_request.user.username, "session_user_a")
        self.assertFalse(
            response.wsgi_request.user.groups.filter(name="Recruiter").exists()
        )
        self.assertTrue(
            response.wsgi_request.user.groups.filter(
                name="Technical Interviewer"
            ).exists()
        )

    def test_logging_in_as_second_user_without_explicit_logout_still_switches(self):
        """Django's login() rotates the session regardless of prior logout
        state -- this documents that logging straight into a second
        account (e.g. if a user never noticed the broken logout button)
        still correctly replaces the identity rather than merging it."""
        client = Client()
        client.login(username="session_user_a", password="pass12345")

        client.login(username="session_user_b", password="pass12345")
        response = client.get(reverse("profile"))
        self.assertEqual(response.wsgi_request.user.username, "session_user_b")


class AnonymousAccessTests(TestCase):
    def test_anonymous_user_redirected_to_login_for_profile(self):
        client = Client()
        response = client.get(reverse("profile"))
        self.assertRedirects(
            response, f"{reverse('login')}?next={reverse('profile')}"
        )

    def test_anonymous_user_cannot_reach_candidate_list(self):
        """CandidateListView sets raise_exception=True, so anonymous
        users get a 403 here rather than a redirect (that's existing,
        pre-existing, intentional behaviour on this view -- unrelated to
        the logout bug -- unlike ProfileView above, which redirects)."""
        client = Client()
        response = client.get(reverse("candidate-list"))
        self.assertEqual(response.status_code, 403)
