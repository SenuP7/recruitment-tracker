"""Keeps the deployed schedule honest.

The housekeeping commands only ever run because .ebextensions/cron.config
names them. Renaming a command, or moving a script, would stop the deletions
the privacy notice promises without anything failing loudly -- so the wiring
is asserted here instead.
"""

import re
from pathlib import Path

from django.core.management import get_commands
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

BASE_DIR = Path(__file__).resolve().parent.parent
CRON_CONFIG = BASE_DIR / ".ebextensions" / "cron.config"
SCRIPT_DIR = BASE_DIR / "scripts" / "housekeeping"
ENV_EXAMPLE = BASE_DIR / ".env.example"
SETTINGS = BASE_DIR / "config" / "settings.py"

SCHEDULED_SCRIPT = re.compile(r"/var/app/current/scripts/housekeeping/(\S+\.sh)")
INVOKED_COMMAND = re.compile(r"^run_command\s+(\S+)", re.MULTILINE)


class HousekeepingScheduleTests(SimpleTestCase):
    def setUp(self):
        self.cron_config = CRON_CONFIG.read_text(encoding="utf-8")

    def test_every_scheduled_script_exists(self):
        scheduled = set(SCHEDULED_SCRIPT.findall(self.cron_config))
        self.assertTrue(scheduled, "cron.config schedules nothing at all.")

        for name in scheduled:
            with self.subTest(script=name):
                self.assertTrue(
                    (SCRIPT_DIR / name).is_file(),
                    f"cron.config schedules {name}, which does not exist.",
                )

    def test_every_script_is_scheduled(self):
        # A script nobody runs is the same failure as a schedule pointing at
        # nothing: the work silently never happens.
        on_disk = {
            path.name
            for path in SCRIPT_DIR.glob("*.sh")
            if not path.name.startswith("_")
        }
        scheduled = set(SCHEDULED_SCRIPT.findall(self.cron_config))

        self.assertEqual(on_disk, scheduled)

    def test_scripts_invoke_real_management_commands(self):
        known = set(get_commands())

        for path in SCRIPT_DIR.glob("*.sh"):
            if path.name.startswith("_"):
                continue
            invoked = INVOKED_COMMAND.findall(path.read_text(encoding="utf-8"))
            with self.subTest(script=path.name):
                self.assertEqual(
                    len(invoked), 1, f"{path.name} should run exactly one command."
                )
                self.assertIn(invoked[0], known)

    def test_scripts_load_the_environment_before_running(self):
        # Without the snapshot the job would fall back to the development
        # SECRET_KEY and no DATABASE_URL, and quietly do nothing useful.
        library = (SCRIPT_DIR / "_lib.sh").read_text(encoding="utf-8")
        self.assertIn("candidflow_env", library)
        self.assertIn("load_environment", library)


ENV_KEY = re.compile(r"^([A-Z_][A-Z0-9_]*)=", re.MULTILINE)
SETTINGS_READS = re.compile(
    r'(?:os\.environ\.get|env_flag)\(\s*"([A-Z_][A-Z0-9_]*)"'
)


class EnvironmentTemplateTests(SimpleTestCase):
    """.env.example is the only record of what a deployment has to set.

    Both of the faults these cover had already happened: settings.py was
    renamed to DJANGO_DEBUG and DJANGO_ALLOWED_HOSTS while a .env still used
    the old names, and the template listed DJANGO_ALLOWED_HOSTS twice with
    the empty one last. Neither failed loudly -- the first stopped the app
    booting at all, the second would have rejected every request.
    """

    def setUp(self):
        self.template = ENV_EXAMPLE.read_text(encoding="utf-8")

    def test_no_variable_is_defined_twice(self):
        keys = ENV_KEY.findall(self.template)
        duplicates = sorted({key for key in keys if keys.count(key) > 1})

        self.assertEqual(
            duplicates,
            [],
            "dotenv keeps the last value it sees, so a duplicate silently "
            "overrides the real one.",
        )

    def test_every_setting_read_is_documented(self):
        # Only this direction: plenty of documented variables are read
        # elsewhere (boto3 reads the AWS_* ones, marketing/views.py the
        # contact addresses), and that is fine.
        read = set(SETTINGS_READS.findall(SETTINGS.read_text(encoding="utf-8")))
        documented = set(ENV_KEY.findall(self.template))

        self.assertEqual(
            sorted(read - documented),
            [],
            "settings.py reads these, but nothing tells a deployer to set them.",
        )


@override_settings(ALLOWED_HOSTS=["candidflow.example"])
class HealthCheckMiddlewareTests(SimpleTestCase):
    """The health check has to answer a request Django would otherwise refuse.

    A load balancer checks its targets by address, so Host is the instance's
    private IP -- never in ALLOWED_HOSTS, and unknowable in advance. Without
    this the first deploy looks correct and cycles unhealthy instances.
    """

    def test_answers_on_a_known_host(self):
        response = self.client.get("/healthz/", HTTP_HOST="candidflow.example")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    def test_answers_on_an_unknown_host(self):
        response = self.client.get("/healthz/", HTTP_HOST="10.0.1.55")

        self.assertEqual(response.status_code, 200)

    def test_other_paths_still_reject_an_unknown_host(self):
        # The bypass is one path wide. If this ever passes, host validation
        # has been switched off for the whole site.
        response = self.client.get("/", HTTP_HOST="10.0.1.55")

        self.assertEqual(response.status_code, 400)

    @override_settings(SECURE_SSL_REDIRECT=True, ALLOWED_HOSTS=["candidflow.example"])
    def test_is_not_redirected_to_https(self):
        # The check runs over plain HTTP; a 301 reads as unhealthy.
        response = self.client.get("/healthz/", HTTP_HOST="candidflow.example")

        self.assertEqual(response.status_code, 200)


@override_settings(
    ALLOWED_HOSTS=["candidflow.example"],
    CLOUDFRONT_ORIGIN_SECRET="a-secret-only-cloudfront-knows",
)
class CloudFrontOriginTests(TestCase):
    """CloudFront holds the certificate; the Elastic Beanstalk hostname has
    none and cannot get one. Without this check the site would be usable
    over plain HTTP by anyone who learned that hostname."""

    HEADER = {"HTTP_X_ORIGIN_VERIFY": "a-secret-only-cloudfront-knows"}

    def test_request_through_cloudfront_is_allowed(self):
        response = self.client.get(
            "/", HTTP_HOST="candidflow.example", **self.HEADER
        )

        self.assertNotEqual(response.status_code, 403)

    def test_request_straight_to_the_origin_is_refused(self):
        response = self.client.get("/", HTTP_HOST="candidflow.example")

        self.assertEqual(response.status_code, 403)

    def test_a_wrong_secret_is_refused(self):
        response = self.client.get(
            "/",
            HTTP_HOST="candidflow.example",
            HTTP_X_ORIGIN_VERIFY="a-secret-only-cloudfront-knows-ish",
        )

        self.assertEqual(response.status_code, 403)

    def test_health_check_still_answers_without_the_header(self):
        # The health check comes from the instance, never through CloudFront.
        # If this ever fails, every deploy rolls back as unhealthy.
        response = self.client.get("/healthz/", HTTP_HOST="10.0.1.55")

        self.assertEqual(response.status_code, 200)

    @override_settings(CLOUDFRONT_ORIGIN_SECRET="")
    def test_no_secret_means_no_check(self):
        # Local work and the test suite must be unaffected.
        response = self.client.get("/", HTTP_HOST="candidflow.example")

        self.assertNotEqual(response.status_code, 403)


class ProxySslHeaderTests(SimpleTestCase):
    """How the origin learns the viewer's connection was encrypted.

    An `X-Forwarded-Proto: https` origin custom header does not survive
    CloudFront -- it manages that header itself -- which produced a redirect
    loop in production: Django saw a plain request, redirected to HTTPS, and
    arrived back at itself. The origin secret carries the same fact and does
    arrive, so it is what marks the request secure.
    """

    def _reload(self, secret):
        # settings.py picks the header at import time, so exercise the same
        # branch rather than asserting on whichever one this process loaded.
        if secret:
            return ("HTTP_X_ORIGIN_VERIFY", secret)
        return ("HTTP_X_FORWARDED_PROTO", "https")

    def test_the_secret_marks_a_request_secure(self):
        header, value = self._reload("a-secret")

        with override_settings(SECURE_PROXY_SSL_HEADER=(header, value)):
            request = RequestFactory().get("/", **{header: value})

            self.assertTrue(request.is_secure())

    def test_a_request_without_the_secret_is_not_secure(self):
        header, value = self._reload("a-secret")

        with override_settings(SECURE_PROXY_SSL_HEADER=(header, value)):
            request = RequestFactory().get("/")

            self.assertFalse(request.is_secure())

    def test_a_forged_forwarded_proto_does_not_mark_it_secure(self):
        # The point of using the secret: X-Forwarded-Proto can be sent by
        # anyone who can reach the origin directly. The secret cannot.
        header, value = self._reload("a-secret")

        with override_settings(SECURE_PROXY_SSL_HEADER=(header, value)):
            request = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https")

            self.assertFalse(request.is_secure())

    def test_without_a_secret_the_conventional_header_applies(self):
        # Local work, the test suite, and an origin reached directly.
        header, value = self._reload("")

        self.assertEqual(header, "HTTP_X_FORWARDED_PROTO")

        with override_settings(SECURE_PROXY_SSL_HEADER=(header, value)):
            request = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https")

            self.assertTrue(request.is_secure())

    def test_settings_wires_the_secret_branch(self):
        # Guards the actual settings.py logic, not just this test's copy.
        source = SETTINGS.read_text(encoding="utf-8")

        self.assertIn('SECURE_PROXY_SSL_HEADER = ("HTTP_X_ORIGIN_VERIFY", CLOUDFRONT_ORIGIN_SECRET)', source)
        self.assertIn('SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")', source)
