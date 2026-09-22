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

from django.contrib.auth.models import Group, Permission, User
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

    def test_post_logout_clears_session_and_redirects_to_landing(self):
        client = Client()
        client.login(username="logout_test_user", password="pass12345")

        response = client.post(self.logout_url)
        self.assertRedirects(response, reverse("landing"))

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
        """Signed-out visitors are sent to sign in, like ProfileView above.

        This used to assert a 403: CandidateListView sets raise_exception=True,
        and Django's PermissionRequiredMixin applied that to anonymous users
        too. That left a signed-out staff member (8-hour idle sessions) on a
        dead-end page with no way to sign in. accounts.mixins.
        PermissionRequiredMixin now redirects them; signed-in users without
        the permission still get 403 (accounts/test_sign_in_redirects.py).
        """
        client = Client()
        response = client.get(reverse("candidate-list"))
        self.assertRedirects(
            response, f"{reverse('login')}?next={reverse('candidate-list')}"
        )


class GlobalSearchTests(TestCase):
    """GlobalSearchView: multi-word matching (same algorithm as the
    dashboard's candidate search), per-category permission gating, and the
    empty-query state."""

    def setUp(self):
        from accounts.models import Department
        from candidates.models import Candidate
        from positions.models import Position

        department = Department.objects.create(name="Engineering")
        self.candidate = Candidate.objects.create(
            first_name="Jane", last_name="Doe", email="jane.doe@example.com", phone="0"
        )
        Candidate.objects.create(
            first_name="John", last_name="Smith", email="john.smith@example.com", phone="0"
        )
        self.position = Position.objects.create(
            title="Backend Engineer", department=department, is_open=True
        )

        self.both_group, _ = Group.objects.get_or_create(name="Recruiter")
        self.both_group.permissions.add(
            Permission.objects.get(codename="view_candidate"),
            Permission.objects.get(codename="view_position"),
        )
        self.both_user = User.objects.create_user("search_both", password="pass12345")
        self.both_user.groups.add(self.both_group)

        self.candidate_only_group, _ = Group.objects.get_or_create(name="Senior Reviewer")
        self.candidate_only_group.permissions.add(Permission.objects.get(codename="view_candidate"))
        self.candidate_only_user = User.objects.create_user("search_cand_only", password="pass12345")
        self.candidate_only_user.groups.add(self.candidate_only_group)

    def test_multi_word_query_matches_full_name(self):
        client = Client()
        client.login(username="search_both", password="pass12345")
        response = client.get(reverse("global-search"), {"q": "Jane Doe"})

        candidates = list(response.context["candidates"])
        self.assertEqual(candidates, [self.candidate])

    def test_single_term_matches_email(self):
        client = Client()
        client.login(username="search_both", password="pass12345")
        response = client.get(reverse("global-search"), {"q": "jane.doe"})

        self.assertEqual(list(response.context["candidates"]), [self.candidate])

    def test_position_title_search(self):
        client = Client()
        client.login(username="search_both", password="pass12345")
        response = client.get(reverse("global-search"), {"q": "Backend"})

        self.assertEqual(list(response.context["positions"]), [self.position])

    def test_no_match_returns_empty(self):
        client = Client()
        client.login(username="search_both", password="pass12345")
        response = client.get(reverse("global-search"), {"q": "Nonexistent Query Xyz"})

        self.assertEqual(list(response.context["candidates"]), [])
        self.assertEqual(list(response.context["positions"]), [])

    def test_empty_query_returns_nothing(self):
        client = Client()
        client.login(username="search_both", password="pass12345")
        response = client.get(reverse("global-search"))

        self.assertEqual(list(response.context["candidates"]), [])
        self.assertEqual(list(response.context["positions"]), [])

    def test_user_without_position_permission_gets_no_position_results(self):
        client = Client()
        client.login(username="search_cand_only", password="pass12345")
        response = client.get(reverse("global-search"), {"q": "Backend"})

        self.assertEqual(list(response.context["positions"]), [])

    def test_user_without_position_permission_still_gets_candidate_results(self):
        client = Client()
        client.login(username="search_cand_only", password="pass12345")
        response = client.get(reverse("global-search"), {"q": "Jane"})

        self.assertEqual(list(response.context["candidates"]), [self.candidate])

    def test_anonymous_user_redirected(self):
        client = Client()
        response = client.get(reverse("global-search"), {"q": "Jane"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
