"""Behaviour behind the rebuilt page layouts: list tabs/search/filters, the
record hubs' per-section permission gating, the dashboard attention rail,
and the small helpers the templates rely on."""

import datetime

from django.contrib.auth.models import Group, Permission, User
from django.template import Context, Template
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department, UserProfile
from accounts.templatetags.ui import initials, percent_of, score_pct
from candidates.models import Application, Candidate
from candidates.views import build_journey
from cv_screening.models import CandidateCV, CVMatchResult, RoleKeywordProfile, Skill
from interviews.models import Interview, InterviewFeedback, StaffNotification
from positions.models import Position


def make_user(username, group_name=None, codenames=(), app_label=None):
    user = User.objects.create_user(username, password="pass12345")
    if group_name:
        group, _ = Group.objects.get_or_create(name=group_name)
        permissions = Permission.objects.filter(codename__in=codenames)
        if app_label:
            permissions = permissions.filter(content_type__app_label=app_label)
        group.permissions.add(*permissions)
        user.groups.add(group)
    return user


class LayoutFixtures(TestCase):
    def setUp(self):
        self.engineering = Department.objects.create(name="Engineering")
        self.security = Department.objects.create(name="Security")
        self.position = Position.objects.create(
            title="Backend Engineer", description="Builds APIs", department=self.engineering, is_open=True
        )
        self.closed_position = Position.objects.create(
            title="Retired Role", description="No longer hiring", department=self.engineering, is_open=False
        )
        self.alice = Candidate.objects.create(
            first_name="Alice", last_name="Wonder", email="alice@example.com", phone="1",
            department=self.engineering, current_status="Applied",
        )
        self.bob = Candidate.objects.create(
            first_name="Bob", last_name="Stone", email="bob@example.com", phone="2",
            department=self.security, current_status="Senior Review",
        )
        self.alice_app = Application.objects.create(candidate=self.alice, position=self.position, status="HR Interview")
        self.bob_app = Application.objects.create(candidate=self.bob, position=self.position, status="Rejected")


# ============================================================
# LIST TOOLBAR
# ============================================================

class CandidateListToolbarTests(LayoutFixtures):
    def setUp(self):
        super().setUp()
        self.user = make_user("recruiter", "Recruiter", ["view_candidate", "view_application"])
        self.client = Client()
        self.client.force_login(self.user)
        self.url = reverse("candidate-list")

    def tab_counts(self, response):
        return {tab["label"]: tab["count"] for tab in response.context["toolbar"]["tabs"]}

    def test_tabs_are_built_from_statuses_in_use_with_counts(self):
        response = self.client.get(self.url)
        self.assertEqual(self.tab_counts(response), {"All": 2, "Applied": 1, "Senior Review": 1})

    def test_tab_filters_the_list(self):
        response = self.client.get(self.url, {"tab": "senior-review"})
        self.assertEqual(list(response.context["candidates"]), [self.bob])

    def test_unknown_tab_falls_back_to_all(self):
        response = self.client.get(self.url, {"tab": "not-a-tab"})
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertEqual(response.context["toolbar"]["active_tab"], "all")

    def test_search_matches_split_names_and_narrows_tab_counts(self):
        response = self.client.get(self.url, {"q": "alice wonder"})
        self.assertEqual(list(response.context["candidates"]), [self.alice])
        self.assertEqual(self.tab_counts(response)["All"], 1)
        self.assertEqual(self.tab_counts(response)["Senior Review"], 0)

    def test_department_filter(self):
        response = self.client.get(self.url, {"dept": self.security.pk})
        self.assertEqual(list(response.context["candidates"]), [self.bob])

    def test_non_numeric_department_is_ignored(self):
        response = self.client.get(self.url, {"dept": "1 OR 1=1"})
        self.assertEqual(response.context["page_obj"].paginator.count, 2)

    def test_invalid_sort_uses_default(self):
        response = self.client.get(self.url, {"sort": "password"})
        self.assertEqual(response.context["toolbar"]["active_sort"], "newest")


class ApplicationListToolbarTests(LayoutFixtures):
    def test_grouped_stage_tabs(self):
        user = make_user("recruiter", "Recruiter", ["view_application"])
        client = Client()
        client.force_login(user)
        response = client.get(reverse("application-list"), {"tab": "interviewing"})
        self.assertEqual(list(response.context["applications"]), [self.alice_app])
        counts = {tab["key"]: tab["count"] for tab in response.context["toolbar"]["tabs"]}
        self.assertEqual(counts["rejected"], 1)
        self.assertEqual(counts["all"], 2)


class PositionListTabTests(LayoutFixtures):
    def test_viewer_without_change_permission_never_sees_closed_positions(self):
        user = make_user("viewer", "Candidate", ["view_position"])
        client = Client()
        client.force_login(user)
        response = client.get(reverse("position-list"), {"tab": "closed"})
        self.assertEqual([t["key"] for t in response.context["toolbar"]["tabs"]], ["open"])
        self.assertTrue(all(p.is_open for p in response.context["positions"]))

    def test_manager_can_switch_to_closed_positions(self):
        user = make_user("manager", "Recruiter", ["view_position", "change_position"])
        client = Client()
        client.force_login(user)
        response = client.get(reverse("position-list"), {"tab": "closed"})
        self.assertEqual(list(response.context["positions"]), [self.closed_position])

    def test_applicant_counts_are_annotated(self):
        user = make_user("viewer", "Recruiter", ["view_position"])
        client = Client()
        client.force_login(user)
        response = client.get(reverse("position-list"))
        position = next(p for p in response.context["positions"] if p.pk == self.position.pk)
        self.assertEqual(position.applicant_count, 2)
        self.assertEqual(response.context["max_applicants"], 2)


class InterviewListTabTests(LayoutFixtures):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.upcoming = Interview.objects.create(
            application=self.alice_app, interview_type="HR", status="Scheduled",
            scheduled_date=now + datetime.timedelta(days=2),
        )
        self.overdue = Interview.objects.create(
            application=self.bob_app, interview_type="Technical", status="Scheduled",
            scheduled_date=now - datetime.timedelta(days=2),
        )
        self.done = Interview.objects.create(
            application=self.bob_app, interview_type="HR", status="Completed",
            scheduled_date=now - datetime.timedelta(days=5),
        )
        self.user = make_user("hr", "HR Interviewer", ["view_interview"])
        self.client = Client()
        self.client.force_login(self.user)

    def test_upcoming_and_overdue_split_on_the_current_time(self):
        upcoming = self.client.get(reverse("interview-list"), {"tab": "upcoming"})
        overdue = self.client.get(reverse("interview-list"), {"tab": "overdue"})
        self.assertEqual(list(upcoming.context["interviews"]), [self.upcoming])
        self.assertEqual(list(overdue.context["interviews"]), [self.overdue])

    def test_type_filter(self):
        response = self.client.get(reverse("interview-list"), {"type": "Technical"})
        self.assertEqual(list(response.context["interviews"]), [self.overdue])

    def test_my_interviews_tabs_stay_scoped_to_the_user(self):
        self.upcoming.interviewer = self.user
        self.upcoming.save()
        response = self.client.get(reverse("my-interviews"))
        self.assertEqual(list(response.context["interviews"]), [self.upcoming])
        counts = {tab["key"]: tab["count"] for tab in response.context["toolbar"]["tabs"]}
        self.assertEqual(counts["all"], 1)
        self.assertEqual(counts["overdue"], 0)


# ============================================================
# RECORD HUBS
# ============================================================

class CandidateHubTests(LayoutFixtures):
    def setUp(self):
        super().setUp()
        Interview.objects.create(
            application=self.alice_app, interview_type="HR", status="Completed",
            scheduled_date=timezone.now() - datetime.timedelta(days=1),
        )
        profile = RoleKeywordProfile.objects.create(role_name="Backend")
        cv = CandidateCV.objects.create(candidate=self.alice)
        self.result = CVMatchResult.objects.create(cv=cv, role_profile=profile, score=0.72)

    def test_staff_sees_every_section_and_a_merged_activity_timeline(self):
        user = make_user(
            "recruiter", "Recruiter",
            ["view_candidate", "view_application", "view_interview", "view_interviewfeedback"],
        )
        client = Client()
        client.force_login(user)
        response = client.get(reverse("candidate-detail", args=[self.alice.pk]))
        self.assertEqual(response.context["applications"], [self.alice_app])
        self.assertEqual(response.context["best_result"], self.result)
        kinds = {event["kind"] for event in response.context["activity"]}
        self.assertTrue({"added", "applied", "interview", "cv"} <= kinds)
        whens = [event["when"] for event in response.context["activity"]]
        self.assertEqual(whens, sorted(whens, reverse=True))

    def test_sections_are_not_queried_without_permission(self):
        user = make_user("candidate_user", "Candidate", ["view_candidate"])
        client = Client()
        client.force_login(user)
        response = client.get(reverse("candidate-detail", args=[self.alice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["applications"], [])
        self.assertEqual(response.context["interviews"], [])
        self.assertIsNone(response.context["best_result"])
        self.assertEqual([event["kind"] for event in response.context["activity"]], ["added"])


class PositionHubTests(LayoutFixtures):
    def test_applicants_are_staff_only(self):
        viewer = make_user("viewer", "Candidate", ["view_position"])
        client = Client()
        client.force_login(viewer)
        response = client.get(reverse("position-detail", args=[self.position.pk]))
        self.assertFalse(response.context["show_applicants"])
        self.assertEqual(response.context["applicants"], [])
        self.assertNotContains(response, "Alice Wonder")

    def test_staff_get_applicants_and_summary(self):
        staff = make_user("recruiter", "Recruiter", ["view_position"])
        client = Client()
        client.force_login(staff)
        response = client.get(reverse("position-detail", args=[self.position.pk]))
        self.assertContains(response, "Alice Wonder")
        self.assertEqual(response.context["summary"]["total"], 2)
        self.assertEqual(response.context["summary"]["interviewing"], 1)


class JourneyTests(TestCase):
    def states(self, status):
        return [step["state"] for step in build_journey(status)]

    def test_in_progress(self):
        self.assertEqual(self.states("HR Interview"), ["done", "done", "current", "upcoming", "upcoming", "upcoming"])

    def test_failed_screening_blocks_later_steps(self):
        self.assertEqual(self.states("CV Screening Failed"), ["done", "failed", "blocked", "blocked", "blocked", "blocked"])

    def test_outcomes(self):
        self.assertEqual(self.states("Accepted")[-1], "done")
        self.assertEqual(self.states("Rejected")[-1], "failed")

    def test_unknown_status_starts_at_the_beginning(self):
        self.assertEqual(self.states("Something Else")[0], "current")


class InterviewHubTests(LayoutFixtures):
    def setUp(self):
        super().setUp()
        self.interview = Interview.objects.create(
            application=self.alice_app, interview_type="HR", status="Scheduled",
            scheduled_date=timezone.now() + datetime.timedelta(days=1),
        )
        author = User.objects.create_user("author", password="pass12345")
        root = InterviewFeedback.objects.create(interview=self.interview, author=author, rating=4, comments="Good", recommendation="Pass")
        InterviewFeedback.objects.create(interview=self.interview, author=author, rating=2, comments="Unsure", recommendation="Hold")
        InterviewFeedback.objects.create(interview=self.interview, author=author, parent=root, rating=None, comments="Agreed")

    def test_feedback_summary_counts_roots_and_replies_separately(self):
        user = make_user("hr", "HR Interviewer", ["view_interview", "view_interviewfeedback"])
        client = Client()
        client.force_login(user)
        summary = client.get(reverse("interview-detail", args=[self.interview.pk])).context["feedback_summary"]
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["replies"], 1)
        self.assertEqual(summary["average"], 3.0)
        self.assertEqual({r["label"]: r["count"] for r in summary["recommendations"]}, {"Pass": 1, "Hold": 1, "Reject": 0})

    def test_feedback_summary_hidden_without_permission(self):
        user = make_user("viewer", "Candidate", ["view_interview"])
        client = Client()
        client.force_login(user)
        response = client.get(reverse("interview-detail", args=[self.interview.pk]))
        self.assertIsNone(response.context["feedback_summary"])
        self.assertNotContains(response, "Unsure")

    def test_feedback_create_is_prefilled_from_querystring(self):
        user = make_user("writer", "HR Interviewer", ["add_interviewfeedback"])
        client = Client()
        client.force_login(user)
        response = client.get(reverse("feedback-create"), {"interview": self.interview.pk})
        self.assertEqual(response.context["form"]["interview"].value(), self.interview.pk)
        self.assertEqual(response.context["context_interview"], self.interview)

    def test_non_numeric_prefill_is_ignored(self):
        user = make_user("writer", "HR Interviewer", ["add_interviewfeedback"])
        client = Client()
        client.force_login(user)
        response = client.get(reverse("feedback-create"), {"interview": "abc"})
        self.assertIsNone(response.context["context_interview"])


# ============================================================
# DASHBOARD
# ============================================================

class DashboardRailTests(LayoutFixtures):
    def setUp(self):
        super().setUp()
        other = Candidate.objects.create(
            first_name="Sam", last_name="Sec", email="sam@example.com", phone="3", department=self.security
        )
        sec_position = Position.objects.create(title="Analyst", description="x", department=self.security)
        self.sec_app = Application.objects.create(candidate=other, position=sec_position, status="Technical Interview")
        soon = timezone.now() + datetime.timedelta(hours=5)
        self.eng_interview = Interview.objects.create(application=self.alice_app, interview_type="HR", scheduled_date=soon)
        self.sec_interview = Interview.objects.create(application=self.sec_app, interview_type="Technical", scheduled_date=soon)

    def test_rail_is_scoped_to_the_users_department(self):
        user = make_user("tech", "Technical Interviewer")
        UserProfile.objects.create(user=user, department=self.engineering)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("dashboard:dashboard"))
        self.assertEqual(response.context["upcoming_interviews"], [self.eng_interview])

    def test_broad_role_sees_all_upcoming_and_interviewing_stat(self):
        user = make_user("recruiter", "Recruiter")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("dashboard:dashboard"))
        self.assertEqual(set(response.context["upcoming_interviews"]), {self.eng_interview, self.sec_interview})
        self.assertEqual(response.context["stats"]["interviewing"], 2)

    def test_pipeline_counts_multiple_applications_in_the_same_stage(self):
        # Regression: ordering leaked into GROUP BY and every stage read as 1.
        Application.objects.create(candidate=self.bob, position=self.position, status="HR Interview")
        user = make_user("recruiter", "Recruiter")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("dashboard:dashboard"))
        pipeline = {step["stage"]: step["count"] for step in response.context["pipeline"]}
        self.assertEqual(pipeline["HR Interview"], 2)
        self.assertEqual(response.context["pipeline_max"], 2)

    def test_results_partial_does_not_build_the_rail(self):
        user = make_user("recruiter", "Recruiter")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("dashboard:dashboard-results"))
        self.assertNotIn("upcoming_interviews", response.context)


# ============================================================
# NOTIFICATIONS / SHELL / HELPERS
# ============================================================

class NotificationUnreadRenderingTests(TestCase):
    def test_unread_items_render_as_new_before_being_marked_read(self):
        user = User.objects.create_user("reader", password="pass12345")
        StaffNotification.objects.create(recipient=user, message="Your feedback was edited by x.")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("staff-notifications"))
        self.assertContains(response, "is-unread")
        self.assertFalse(StaffNotification.objects.filter(recipient=user, is_read=False).exists())


class ShellTests(TestCase):
    def test_favicon_ico_redirects_to_static_asset(self):
        response = Client().get("/favicon.ico")
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].endswith("img/favicon.ico"))

    def test_quick_create_menu_only_lists_permitted_items(self):
        user = make_user("limited", "Recruiter", ["view_candidate", "add_candidate"], app_label="candidates")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("candidate-list"))
        self.assertContains(response, reverse("candidate-create"))
        self.assertNotContains(response, reverse("interview-create"))


class TemplateHelperTests(TestCase):
    def test_initials(self):
        self.assertEqual(initials("alice wonder"), "AW")
        self.assertEqual(initials("admin"), "AD")
        self.assertEqual(initials(""), "?")
        self.assertEqual(initials(None), "?")

    def test_percent_of_is_safe(self):
        self.assertEqual(percent_of(3, 4), 75)
        self.assertEqual(percent_of(5, 0), 0)
        self.assertEqual(percent_of(9, 3), 100)
        self.assertEqual(percent_of("x", 3), 0)

    def test_nonzero_drops_empty_cascade_items(self):
        from accounts.templatetags.ui import nonzero

        self.assertEqual(nonzero([("reply", "replies", 0), ("interview", "interviews", 2)]), [("interview", "interviews", 2)])
        self.assertEqual(nonzero(None), [])

    def test_score_pct(self):
        self.assertEqual(score_pct(0.856), 86)
        self.assertIsNone(score_pct(None))

    def test_url_replace_keeps_other_params_and_drops_empty_values(self):
        request = RequestFactory().get("/candidates/", {"tab": "applied", "q": "ann", "page": "3"})
        rendered = Template("{% load ui %}{% url_replace page='' tab='hired' %}").render(Context({"request": request}))
        self.assertIn("tab=hired", rendered)
        self.assertIn("q=ann", rendered)
        self.assertNotIn("page=", rendered)
