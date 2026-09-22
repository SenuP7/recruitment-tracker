import os
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from candidates.models import Application, Candidate, CandidateInvite, PendingApplication
from cv_screening.models import CVMatchResult
from interviews.models import Interview, InterviewFeedback

DEMO_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


DEMO_PASSWORD = "seed-demo-test-pw-42"


@override_settings(STORAGES=DEMO_STORAGES)
@mock.patch.dict(os.environ, {"CANDIDFLOW_DEMO_PASSWORD": DEMO_PASSWORD})
class SeedDemoTests(TestCase):
    def seed(self, *args):
        out = StringIO()
        call_command("seed_demo", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_no_password_is_baked_into_the_repository(self):
        """A copy of the repo must not hand anyone a working login."""
        from pathlib import Path

        source = Path(__file__).resolve().parent.joinpath(
            "management", "commands", "seed_demo.py"
        ).read_text()
        self.assertNotIn("demo-pass", source)
        self.assertIn("secrets.token_urlsafe", source)

    def test_a_generated_password_is_printed_and_works(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CANDIDFLOW_DEMO_PASSWORD", None)
            output = self.seed()
        printed = output.split("password for all of them: ")[1].split(")")[0]
        self.assertGreater(len(printed), 12)
        self.assertTrue(self.client.login(username="demo.recruiter", password=printed))

    def test_it_builds_one_worked_example_end_to_end(self):
        self.seed("--with-permissions")

        candidate = Candidate.objects.get(email="maya@demo.candidflow.example")
        application = Application.objects.get(candidate=candidate)

        self.assertEqual(application.status, "Technical Interview")
        self.assertTrue(application.applicant_message)
        self.assertIsNotNone(candidate.user)

        result = CVMatchResult.objects.get(cv__candidate=candidate)
        self.assertGreater(result.score, 0)
        self.assertTrue(result.missing_required.exists(), "a missing skill makes the demo useful")

        rounds = Interview.objects.filter(application=application)
        self.assertEqual(rounds.filter(status="Completed").count(), 1)
        self.assertEqual(rounds.filter(status="Scheduled").count(), 1)
        # Scoped to this application on purpose: the seeder also builds a
        # six-applicant cohort on a second role, which has feedback of its
        # own. A global count here would assert something the test does not
        # actually care about.
        worked_example = InterviewFeedback.objects.filter(interview__application=application)
        self.assertEqual(worked_example.filter(parent__isnull=True).count(), 1)
        self.assertEqual(worked_example.filter(parent__isnull=False).count(), 1)

        # The other two flows are represented too.
        self.assertTrue(PendingApplication.objects.filter(email__endswith="demo.candidflow.example").exists())
        self.assertTrue(CandidateInvite.objects.filter(candidate=candidate).exists())

    def test_every_role_gets_a_working_login(self):
        self.seed("--with-permissions")
        application = Application.objects.get(candidate__email="maya@demo.candidflow.example")

        for username in ("demo.recruiter", "demo.hr", "demo.tech", "demo.senior", "demo.lead"):
            with self.subTest(user=username):
                self.assertTrue(self.client.login(username=username, password=DEMO_PASSWORD))
                response = self.client.get(reverse("application-detail", args=[application.pk]))
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_the_candidate_login_reaches_their_own_portal(self):
        self.seed("--with-permissions")
        self.assertTrue(
            self.client.login(username="maya@demo.candidflow.example", password=DEMO_PASSWORD)
        )
        response = self.client.get(reverse("portal:overview"))
        self.assertContains(response, "Backend Engineer")
        self.assertNotContains(response, "Excellent Match")

    def test_running_it_twice_replaces_rather_than_duplicates(self):
        self.seed()
        first = (Candidate.objects.count(), User.objects.count(), Application.objects.count())
        self.seed()
        self.assertEqual(
            (Candidate.objects.count(), User.objects.count(), Application.objects.count()), first
        )

    def test_clear_removes_only_demo_data(self):
        keeper = Candidate.objects.create(
            first_name="Real", last_name="Person", email="real@example.com", phone="1"
        )
        self.seed()
        self.seed("--clear")

        self.assertFalse(Candidate.objects.filter(email__endswith="demo.candidflow.example").exists())
        self.assertFalse(User.objects.filter(username__startswith="demo.").exists())
        self.assertTrue(Candidate.objects.filter(pk=keeper.pk).exists())

    def test_permissions_are_left_alone_unless_asked_for(self):
        group = Group.objects.create(name="Recruiter")
        self.seed()
        self.assertEqual(group.permissions.count(), 0)

        self.seed("--with-permissions")
        self.assertGreater(group.permissions.count(), 0)
        # The portal needs none, so the Candidate group stays empty.
        self.assertEqual(Group.objects.get(name="Candidate").permissions.count(), 0)

    def test_every_seeded_role_gets_real_permissions(self):
        """Every role a demo login signs into must hold permissions.

        seed_demo used to keep its own copy of the matrix, which never gained
        Department Chief or Administrator, so both logins reached the
        dashboard and hit 403 on every page past it. It now runs
        assign_role_permissions, so the two can't drift again.
        """
        self.seed("--with-permissions")

        for name in ("Recruiter", "HR Interviewer", "Technical Interviewer", "Senior Reviewer",
                     "Leadership Manager", "Department Chief", "Administrator"):
            self.assertGreater(Group.objects.get(name=name).permissions.count(), 0, name)

        chief = User.objects.get(username="demo.chief")
        admin = User.objects.get(username="demo.admin")
        self.assertTrue(chief.has_perm("interviews.view_interview"))
        self.assertTrue(admin.has_perm("candidates.add_candidate"))

    def test_seeded_permissions_match_the_production_command_exactly(self):
        """Nothing left to drift: --with-permissions gives each role exactly
        what assign_role_permissions gives it."""
        self.seed("--with-permissions")
        seeded = {g.name: set(g.permissions.values_list("codename", flat=True)) for g in Group.objects.all()}

        for group in Group.objects.all():
            group.permissions.clear()
        call_command("assign_role_permissions", stdout=StringIO())
        production = {g.name: set(g.permissions.values_list("codename", flat=True)) for g in Group.objects.all()}

        self.assertEqual(seeded, production)

    @override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "x"}})
    def test_it_refuses_a_non_sqlite_database_without_confirmation(self):
        with self.assertRaises(CommandError) as refusal:
            call_command("seed_demo", stdout=StringIO())
        self.assertIn("--yes", str(refusal.exception))

    @override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "x"}})
    def test_refusing_to_clear_tells_you_how_to_clear(self):
        """The refusal has to name the command you actually wanted. Saying
        'writes demo data ... re-run with --yes' sends you off to re-seed."""
        with self.assertRaises(CommandError) as refusal:
            call_command("seed_demo", "--clear", stdout=StringIO())
        message = str(refusal.exception)
        self.assertIn("--clear --yes", message)
        self.assertIn("deletes", message)


class SeedDemoCohortTests(TestCase):
    """The six-applicant cohort on the second role.

    Its value is entirely in the spread: a pipeline where every candidate
    scores the same, or sits at the same stage, demonstrates nothing about
    what screening and stages are for.
    """

    def seed(self, *args):
        call_command("seed_demo", *args, stdout=StringIO(), stderr=StringIO())

    def test_the_cohort_spans_the_pipeline_with_varied_scores(self):
        from positions.models import Position

        self.seed()

        position = Position.objects.get(title="Platform Engineer")
        applications = Application.objects.filter(position=position)

        self.assertEqual(applications.count(), 6)

        # Several distinct stages, not six copies of one.
        self.assertGreaterEqual(len({a.status for a in applications}), 5)

        scores = set(
            CVMatchResult.objects.filter(
                cv__candidate__in=[a.candidate for a in applications]
            ).values_list("score", flat=True)
        )
        self.assertEqual(
            CVMatchResult.objects.filter(
                cv__candidate__in=[a.candidate for a in applications]
            ).count(),
            6,
            "every applicant needs a real scored CV, not a placeholder",
        )
        self.assertGreaterEqual(len(scores), 3, "the scores must actually differ")

    def test_the_cohort_has_interviews_and_feedback(self):
        from positions.models import Position

        self.seed()

        position = Position.objects.get(title="Platform Engineer")
        rounds = Interview.objects.filter(application__position=position)

        self.assertTrue(rounds.filter(status="Completed").exists())
        self.assertTrue(rounds.filter(status="Scheduled").exists())
        self.assertTrue(
            InterviewFeedback.objects.filter(interview__in=rounds, parent__isnull=True).exists()
        )

    def test_clear_removes_the_cohort_too(self):
        from positions.models import Position

        self.seed()
        self.assertTrue(Position.objects.filter(title="Platform Engineer").exists())

        self.seed("--clear")

        self.assertFalse(
            Position.objects.filter(title="Platform Engineer").exists(),
            "the cohort must be tagged like everything else, or --clear leaves it behind",
        )
        self.assertFalse(
            Candidate.objects.filter(email__endswith="demo.candidflow.example").exists()
        )
