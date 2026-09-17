from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.views.defaults import server_error

from . import status
from .views import PUBLIC_PAGES

DOC_PAGES = ("privacy", "terms", "cookies", "security", "accessibility", "candidate-notice")


class PublicPagesTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_every_public_page_renders(self):
        for name in PUBLIC_PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="site-footer"')

    def test_landing_has_no_same_page_links(self):
        # The keyboard skip link is the one intentional in-page link.
        content = self.client.get(reverse("landing")).content.decode()
        content = content.replace('<a class="skip-link" href="#main">', "")
        self.assertNotIn('href="#', content)

    def test_nav_and_footer_link_to_real_pages(self):
        response = self.client.get(reverse("landing"))
        for name in ("help", "status", "security", "privacy", "terms", "cookies", "accessibility", "candidate-notice", "login"):
            with self.subTest(link=name):
                self.assertContains(response, f'href="{reverse(name)}"')

    def test_active_nav_link_is_marked(self):
        response = self.client.get(reverse("privacy"))
        self.assertContains(response, f'<a href="{reverse("privacy")}" aria-current="page">Privacy</a>', html=False)

    def test_doc_pages_have_table_of_contents_matching_sections(self):
        for name in DOC_PAGES:
            with self.subTest(page=name):
                content = self.client.get(reverse(name)).content.decode()
                self.assertIn("On this page", content)
                toc = content.split('<ol>', 1)[1].split('</ol>', 1)[0]
                for anchor in [part.split('"', 1)[0] for part in toc.split('href="#')[1:]]:
                    self.assertIn(f'id="{anchor}"', content)

    def test_logged_in_visitor_sees_open_app_instead_of_log_in(self):
        user = User.objects.create_user("public_viewer", password="pw-12345-long")
        self.client.force_login(user)
        response = self.client.get(reverse("landing"))
        self.assertContains(response, "Open Candidflow")
        self.assertContains(response, f'href="{reverse("profile")}"')

    def test_screening_thresholds_in_copy_match_the_code(self):
        # The notices disclose the automatic pass/fail thresholds; keep them honest.
        from pathlib import Path
        source = Path(__file__).resolve().parent.parent.joinpath("cv_screening", "views.py").read_text()
        self.assertIn("result.score >= 0.7", source)
        self.assertIn("result.score < 0.4", source)
        for name in ("privacy", "candidate-notice", "help"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, "70%")
                self.assertContains(response, "40%")


class StatusChecksTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_status_page_runs_live_checks_without_leaking_config(self):
        response = self.client.get(reverse("status"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertContains(response, "All systems operational")
        self.assertContains(response, "Database")
        from django.conf import settings
        self.assertNotContains(response, settings.AWS_STORAGE_BUCKET_NAME)

    def test_database_failure_reports_outage(self):
        with mock.patch.object(status, "_check_database", return_value={"name": "Database", "description": "", "state": status.OUTAGE, "detail": "Not reachable"}):
            response = self.client.get(reverse("status"))
        self.assertContains(response, "Service disruption")

    def test_inactive_notifications_do_not_degrade_overall(self):
        checks = [
            {"name": "Web application", "state": status.OPERATIONAL},
            {"name": "Database", "state": status.OPERATIONAL},
            {"name": "Email notifications", "state": status.INACTIVE},
        ]
        self.assertEqual(status.overall_state(checks), status.OPERATIONAL)
        checks.append({"name": "CV storage", "state": status.DEGRADED})
        self.assertEqual(status.overall_state(checks), status.DEGRADED)

    @override_settings(NOTIFICATIONS_LOCAL_MODE=True)
    def test_local_notification_mode_is_reported(self):
        check = status._check_notifications()
        self.assertEqual(check["state"], status.INACTIVE)
        self.assertIn("Local mode", check["detail"])

    def test_footer_status_is_cached(self):
        status.footer_status()
        with mock.patch.object(status, "run_checks") as run_checks:
            self.client.get(reverse("privacy"))
            run_checks.assert_not_called()


class CrawlerFilesTests(TestCase):
    def test_robots_disallows_the_app_and_points_to_sitemap(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response["Content-Type"], "text/plain")
        body = response.content.decode()
        for prefix in ("/dashboard/", "/candidates/", "/accounts/", "/admin/"):
            self.assertIn(f"Disallow: {prefix}", body)
        self.assertIn("Sitemap: http://testserver/sitemap.xml", body)

    def test_sitemap_lists_only_public_pages(self):
        body = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("<loc>http://testserver/privacy/</loc>", body)
        self.assertNotIn("dashboard", body)

    def test_security_txt_has_required_fields(self):
        body = self.client.get("/.well-known/security.txt").content.decode()
        self.assertIn("Contact: mailto:security@", body)
        self.assertIn("Expires: ", body)

    def test_app_and_login_pages_are_noindex(self):
        self.assertContains(self.client.get(reverse("login")), 'name="robots" content="noindex, nofollow"')
        user = User.objects.create_superuser("noindex_admin", "a@example.com", "pw-12345-long")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("profile")), 'name="robots" content="noindex, nofollow"')


class ErrorPagesTests(TestCase):
    def test_404_uses_branded_page(self):
        response = self.client.get("/definitely-not-a-page/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "We couldn't find that page.", status_code=404)

    def test_500_renders_without_request_context(self):
        request = RequestFactory().get("/")
        response = server_error(request)
        self.assertEqual(response.status_code, 500)
        self.assertIn(b"Something went wrong on our side.", response.content)
