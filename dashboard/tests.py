from django.contrib.auth.models import Group, Permission, User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Department, UserProfile
from candidates.models import Application, Candidate
from cv_screening.models import CVMatchResult, CandidateCV, RoleKeywordProfile, Skill
from positions.models import Position


class DashboardTestBase(TestCase):
    """Shared fixtures: two departments, one candidate/application/position
    per department, a CV + match result for the Engineering candidate only
    (Security's candidate deliberately has no CV, to exercise the
    missing-CV-doesn't-crash requirement)."""

    def setUp(self):
        # ---------------------------------------------------------
        # DEPARTMENTS
        # ---------------------------------------------------------
        self.dept_engineering = Department.objects.create(name="Engineering Test")
        self.dept_security = Department.objects.create(name="Security Test")

        # ---------------------------------------------------------
        # GROUPS (mirrors the real DB's manually-created groups --
        # get_or_create so this is safe to run against any DB state)
        # ---------------------------------------------------------
        self.group_recruiter, _ = Group.objects.get_or_create(name="Recruiter")
        self.group_recruiter.permissions.add(
            *Permission.objects.filter(
                content_type__app_label="candidates",
                codename__in=["view_candidate", "view_application"],
            )
        )
        self.group_tech, _ = Group.objects.get_or_create(name="Technical Interviewer")
        self.group_candidate, _ = Group.objects.get_or_create(name="Candidate")
        # Matches the real DB's Candidate group permissions, so tests that
        # exercise permission-gated views (e.g. candidate-list) behave the
        # same way a real Candidate-group account would.
        self.group_candidate.permissions.add(
            *Permission.objects.filter(
                content_type__app_label="candidates",
                codename__in=["view_candidate", "view_application"],
            )
        )

        # ---------------------------------------------------------
        # USERS
        # ---------------------------------------------------------
        self.recruiter_user = User.objects.create_user("recruiter_t", password="pass12345")
        self.recruiter_user.groups.add(self.group_recruiter)

        self.tech_user_eng = User.objects.create_user("tech_eng_t", password="pass12345")
        self.tech_user_eng.groups.add(self.group_tech)
        UserProfile.objects.create(user=self.tech_user_eng, department=self.dept_engineering)

        self.tech_user_no_dept = User.objects.create_user("tech_nodept_t", password="pass12345")
        self.tech_user_no_dept.groups.add(self.group_tech)
        UserProfile.objects.create(user=self.tech_user_no_dept, department=None)

        self.candidate_group_user = User.objects.create_user("candidate_t", password="pass12345")
        self.candidate_group_user.groups.add(self.group_candidate)

        self.superuser = User.objects.create_superuser("admin_t", password="pass12345")

        # ---------------------------------------------------------
        # ROLE PROFILE + SKILLS (Engineering position only)
        # ---------------------------------------------------------
        self.skill_python = Skill.objects.create(name="Python Test")
        self.role_profile = RoleKeywordProfile.objects.create(role_name="Engineer Test")
        self.role_profile.required_skills.add(self.skill_python)

        # ---------------------------------------------------------
        # POSITIONS
        # ---------------------------------------------------------
        self.position_eng = Position.objects.create(
            title="Engineer Test",
            description="desc",
            minimum_experience=1,
            department=self.dept_engineering,
            screening_profile=self.role_profile,
            is_open=True,
        )
        self.position_sec = Position.objects.create(
            title="Security Analyst Test",
            description="desc",
            minimum_experience=1,
            department=self.dept_security,
            is_open=True,
        )

        # ---------------------------------------------------------
        # CANDIDATES + APPLICATIONS
        # ---------------------------------------------------------
        self.candidate_eng = Candidate.objects.create(
            first_name="Eng",
            last_name="Candidate",
            email="eng.candidate@example.com",
            phone="0710000001",
            department=self.dept_engineering,
        )
        self.candidate_sec = Candidate.objects.create(
            first_name="Sec",
            last_name="Candidate",
            email="sec.candidate@example.com",
            phone="0710000002",
            department=self.dept_security,
        )

        self.application_eng = Application.objects.create(
            candidate=self.candidate_eng,
            position=self.position_eng,
            status="CV Screening Passed",
        )
        self.application_sec = Application.objects.create(
            candidate=self.candidate_sec,
            position=self.position_sec,
            status="Applied",
        )

        # ---------------------------------------------------------
        # CV + MATCH RESULT (Engineering candidate only)
        # ---------------------------------------------------------
        self.cv_eng = CandidateCV.objects.create(candidate=self.candidate_eng)
        self.match_result_eng = CVMatchResult.objects.create(
            cv=self.cv_eng,
            role_profile=self.role_profile,
            score=0.85,
        )
        self.match_result_eng.matched_required.add(self.skill_python)

        self.dashboard_url = reverse("dashboard:dashboard")
        self.results_url = reverse("dashboard:dashboard-results")


class AnonymousAccessTests(DashboardTestBase):
    def test_anonymous_user_cannot_access_dashboard(self):
        client = Client()
        response = client.get(self.dashboard_url)
        self.assertNotEqual(response.status_code, 200)


class RBACTests(DashboardTestBase):
    def test_recruiter_sees_both_departments(self):
        client = Client()
        client.login(username="recruiter_t", password="pass12345")
        response = client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertIn(self.candidate_eng.id, candidate_ids)
        self.assertIn(self.candidate_sec.id, candidate_ids)

    def test_technical_interviewer_sees_only_own_department(self):
        client = Client()
        client.login(username="tech_eng_t", password="pass12345")
        response = client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertIn(self.candidate_eng.id, candidate_ids)
        self.assertNotIn(self.candidate_sec.id, candidate_ids)

    def test_technical_interviewer_cannot_leak_other_department_via_filter(self):
        """Selecting another department in the filter must not widen scope --
        it should just return zero results, since RBAC is enforced at the
        queryset level before filters are ever applied."""
        client = Client()
        client.login(username="tech_eng_t", password="pass12345")
        response = client.get(self.dashboard_url, {"department": self.dept_security.id})
        self.assertEqual(response.status_code, 200)
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertNotIn(self.candidate_sec.id, candidate_ids)

    def test_technical_interviewer_without_department_gets_empty_state_not_crash(self):
        client = Client()
        client.login(username="tech_nodept_t", password="pass12345")
        response = client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["department_missing"])
        self.assertEqual(response.context["rows"], [])

    def test_candidate_group_denied_dashboard_access(self):
        client = Client()
        client.login(username="candidate_t", password="pass12345")
        response = client.get(self.dashboard_url)
        self.assertNotEqual(response.status_code, 200)

    def test_superuser_sees_everything(self):
        client = Client()
        client.login(username="admin_t", password="pass12345")
        response = client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertIn(self.candidate_eng.id, candidate_ids)
        self.assertIn(self.candidate_sec.id, candidate_ids)


class FilterTests(DashboardTestBase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.login(username="recruiter_t", password="pass12345")

    def test_department_filter(self):
        response = self.client.get(self.dashboard_url, {"department": self.dept_engineering.id})
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertEqual(candidate_ids, {self.candidate_eng.id})

    def test_status_filter(self):
        response = self.client.get(self.dashboard_url, {"status": "Applied"})
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertEqual(candidate_ids, {self.candidate_sec.id})

    def test_position_filter(self):
        response = self.client.get(self.dashboard_url, {"position": self.position_sec.id})
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertEqual(candidate_ids, {self.candidate_sec.id})

    def test_combined_filters_intersect(self):
        response = self.client.get(
            self.dashboard_url,
            {"department": self.dept_engineering.id, "status": "CV Screening Passed"},
        )
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertEqual(candidate_ids, {self.candidate_eng.id})

        # Same department, wrong status -> no match.
        response = self.client.get(
            self.dashboard_url,
            {"department": self.dept_engineering.id, "status": "Rejected"},
        )
        self.assertEqual(response.context["rows"], [])

    def test_invalid_filter_values_are_ignored_not_fatal(self):
        response = self.client.get(
            self.dashboard_url,
            {"department": "not-a-number", "status": "not-a-real-status"},
        )
        self.assertEqual(response.status_code, 200)

    def test_overview_stats_reflect_active_filters(self):
        unfiltered = self.client.get(self.dashboard_url)
        self.assertEqual(unfiltered.context["stats"]["total_candidates"], 2)
        self.assertEqual(unfiltered.context["stats"]["total_applications"], 2)

        filtered = self.client.get(
            self.dashboard_url, {"department": self.dept_engineering.id}
        )
        self.assertEqual(filtered.context["stats"]["total_candidates"], 1)
        self.assertEqual(filtered.context["stats"]["total_applications"], 1)
        self.assertEqual(filtered.context["stats"]["open_positions"], 1)

    def test_pipeline_counts_reflect_active_filters(self):
        filtered = self.client.get(self.dashboard_url, {"status": "Applied"})
        pipeline = {step["stage"]: step["count"] for step in filtered.context["pipeline"]}
        self.assertEqual(pipeline["Applied"], 1)
        self.assertEqual(pipeline["CV Screening Passed"], 0)

    def test_search_by_name(self):
        response = self.client.get(self.dashboard_url, {"search": "Sec Candidate"})
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertEqual(candidate_ids, {self.candidate_sec.id})


class CVIntegrationTests(DashboardTestBase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.login(username="recruiter_t", password="pass12345")

    def test_cv_score_appears_for_screened_candidate(self):
        response = self.client.get(self.dashboard_url)
        row = next(
            r for r in response.context["rows"]
            if r["application"].candidate_id == self.candidate_eng.id
        )
        self.assertEqual(row["score_percent"], 85)
        self.assertEqual(row["match_category"], "Excellent Match")

    def test_missing_cv_does_not_crash_dashboard(self):
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        row = next(
            r for r in response.context["rows"]
            if r["application"].candidate_id == self.candidate_sec.id
        )
        self.assertIsNone(row["score_percent"])
        self.assertIsNone(row["match_category"])

    def test_score_range_filter(self):
        response = self.client.get(self.dashboard_url, {"score_min": "90"})
        self.assertEqual(response.context["rows"], [])

        response = self.client.get(self.dashboard_url, {"score_min": "50"})
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertIn(self.candidate_eng.id, candidate_ids)

    def test_match_category_filter(self):
        response = self.client.get(self.dashboard_url, {"category": "excellent"})
        candidate_ids = {row["application"].candidate_id for row in response.context["rows"]}
        self.assertEqual(candidate_ids, {self.candidate_eng.id})


class PaginationTests(DashboardTestBase):
    def test_pagination_limits_page_size(self):
        for i in range(30):
            candidate = Candidate.objects.create(
                first_name=f"Bulk{i}",
                last_name="Candidate",
                email=f"bulk{i}@example.com",
                phone="0710000000",
                department=self.dept_engineering,
            )
            Application.objects.create(
                candidate=candidate,
                position=self.position_eng,
                status="Applied",
            )

        client = Client()
        client.login(username="recruiter_t", password="pass12345")
        response = client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.context["rows"]), 25)
        self.assertTrue(response.context["page_obj"].paginator.num_pages >= 2)

    def test_second_page_is_reachable(self):
        for i in range(30):
            candidate = Candidate.objects.create(
                first_name=f"Bulk{i}",
                last_name="Candidate",
                email=f"bulk2{i}@example.com",
                phone="0710000000",
                department=self.dept_engineering,
            )
            Application.objects.create(
                candidate=candidate,
                position=self.position_eng,
                status="Applied",
            )

        client = Client()
        client.login(username="recruiter_t", password="pass12345")
        response = client.get(self.results_url, {"page": 2})
        self.assertEqual(response.status_code, 200)


class NavLinkAccessTests(DashboardTestBase):
    """The shared nav's logo/Dashboard link must never point somewhere
    the current user would get a 403 from -- see context_processors.py."""

    def test_recruiter_gets_dashboard_link(self):
        client = Client()
        client.login(username="recruiter_t", password="pass12345")
        response = client.get(reverse("candidate-list"))
        self.assertTrue(response.context["can_access_dashboard"])
        self.assertContains(response, reverse("dashboard:dashboard"))

    def test_candidate_group_does_not_get_dashboard_link(self):
        client = Client()
        client.login(username="candidate_t", password="pass12345")
        response = client.get(reverse("candidate-list"))
        self.assertFalse(response.context["can_access_dashboard"])
        self.assertNotContains(response, reverse("dashboard:dashboard"))
