from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Avg, Count, Q
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.text import slugify
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from accounts.decorators import user_in_groups
from accounts.listing import ListToolbarMixin, Tab
from accounts.models import Department
from cv_screening.models import CVMatchResult

from .models import Candidate, Application

# Known candidate/application stages in pipeline order -- used to order tabs.
STAGE_ORDER = [choice[0] for choice in Application.STATUS_CHOICES]

APPLICATION_TAB_GROUPS = [
    ("applied", "Applied", ["Applied"]),
    ("screening", "Screening", ["CV Screening", "CV Screening Passed", "CV Screening Failed"]),
    ("interviewing", "Interviewing", ["HR Interview", "Technical Interview"]),
    ("review", "Senior review", ["Senior Review"]),
    ("accepted", "Accepted", ["Accepted"]),
    ("rejected", "Rejected", ["Rejected"]),
]

# The linear path an application moves along. Every status maps onto one
# step; terminal failures stop the path at the step where they happened.
JOURNEY_STEPS = ["Applied", "CV screening", "HR interview", "Technical interview", "Senior review", "Decision"]
STATUS_TO_STEP = {
    "Applied": (0, None),
    "CV Screening": (1, None),
    "CV Screening Passed": (1, "done"),
    "CV Screening Failed": (1, "failed"),
    "HR Interview": (2, None),
    "Technical Interview": (3, None),
    "Senior Review": (4, None),
    "Accepted": (5, "done"),
    "Rejected": (5, "failed"),
}


def build_journey(status):
    index, outcome = STATUS_TO_STEP.get(status, (0, None))
    steps = []
    for position, label in enumerate(JOURNEY_STEPS):
        if position < index:
            state = "done"
        elif position == index:
            state = outcome or "current"
        else:
            state = "blocked" if outcome == "failed" else "upcoming"
        steps.append({"label": label, "state": state})
    return steps


def _latest_cv_result(candidate, position):
    if position is None or position.screening_profile_id is None:
        return None
    return (
        CVMatchResult.objects.filter(cv__candidate=candidate, role_profile_id=position.screening_profile_id)
        .select_related("role_profile", "cv")
        .prefetch_related("matched_required", "matched_nice_to_have", "missing_required")
        .order_by("-computed_at")
        .first()
    )


def _skill_coverage(result):
    if result is None:
        return None
    matched = result.matched_required.count()
    missing = result.missing_required.count()
    total = matched + missing
    return {"matched": matched, "total": total}


# ============================================================
# CANDIDATE VIEWS
# ============================================================

class CandidateListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListToolbarMixin,
    ListView
):
    model = Candidate
    template_name = "candidates/candidate_list.html"
    context_object_name = "candidates"
    paginate_by = 25

    permission_required = "candidates.view_candidate"
    raise_exception = True

    search_fields = ("first_name", "last_name", "email")
    search_placeholder = "Search by name or email"
    sort_options = {
        "newest": ("Newest", ("-id",)),
        "oldest": ("Oldest", ("id",)),
        "name": ("Name A-Z", ("first_name", "last_name", "id")),
    }
    default_sort = "newest"

    def get_base_queryset(self):
        return Candidate.objects.select_related("department").annotate(
            application_count=Count("applications", distinct=True)
        )

    def get_tabs(self):
        # current_status is free text, so tabs come from the values actually in
        # use, ordered by the known pipeline and then alphabetically.
        statuses = set(Candidate.objects.values_list("current_status", flat=True))
        ordered = sorted(
            statuses,
            key=lambda s: (STAGE_ORDER.index(s) if s in STAGE_ORDER else len(STAGE_ORDER), s),
        )
        return [Tab("all", "All")] + [
            Tab(slugify(status) or "blank", status or "No status", Q(current_status=status))
            for status in ordered
        ]

    def apply_extra_filters(self, queryset):
        department = self.request.GET.get("dept", "").strip()
        self.active_department = department if department.isdigit() else ""
        if self.active_department:
            queryset = queryset.filter(department_id=self.active_department)
        return queryset

    def get_extra_toolbar_context(self):
        return {
            "departments": Department.objects.order_by("name"),
            "active_department": self.active_department,
        }


class CandidateDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DetailView
):
    """Record hub. Each related section is only queried when the user's own
    permissions cover it, so the page never surfaces data the rest of the app
    would refuse to show them."""

    model = Candidate
    template_name = "candidates/candidate_detail.html"
    context_object_name = "candidate"

    permission_required = "candidates.view_candidate"
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        candidate = self.object
        now = timezone.now()

        can_view_applications = user.has_perm("candidates.view_application")
        can_view_interviews = user.has_perm("interviews.view_interview")
        can_view_feedback = user.has_perm("interviews.view_interviewfeedback")
        can_view_cv = user_in_groups(user)

        applications = []
        if can_view_applications:
            applications = list(
                candidate.applications.select_related("position", "position__department")
                .annotate(interview_count=Count("interviews", distinct=True))
                .order_by("-applied_at")
            )

        interviews = []
        if can_view_interviews:
            from interviews.models import Interview

            interviews = list(
                Interview.objects.filter(application__candidate=candidate)
                .select_related("application__position", "interviewer")
                .annotate(feedback_count=Count("feedback_entries", filter=Q(feedback_entries__parent__isnull=True)))
                .order_by("scheduled_date")
            )

        cv_results = []
        if can_view_cv:
            cv_results = list(
                CVMatchResult.objects.filter(cv__candidate=candidate)
                .select_related("role_profile", "cv")
                .order_by("-computed_at")
            )

        feedback = []
        if can_view_feedback:
            from interviews.models import InterviewFeedback

            feedback = list(
                InterviewFeedback.objects.filter(interview__application__candidate=candidate, parent__isnull=True)
                .select_related("author", "interview")
                .order_by("-created_at")
            )

        activity = [{"when": candidate.created_at, "kind": "added", "title": "Added to Candidflow", "detail": ""}]
        for application in applications:
            activity.append({
                "when": application.applied_at,
                "kind": "applied",
                "title": f"Applied for {application.position.title}",
                "detail": application.position.department.name if application.position.department_id else "",
                "link": reverse("application-detail", args=[application.pk]),
            })
        for interview in interviews:
            if interview.scheduled_date <= now:
                activity.append({
                    "when": interview.scheduled_date,
                    "kind": "interview",
                    "title": f"{interview.interview_type} interview",
                    "detail": f"{interview.application.position.title} · {interview.status}",
                    "link": reverse("interview-detail", args=[interview.pk]),
                })
        for result in cv_results:
            activity.append({
                "when": result.computed_at,
                "kind": "cv",
                "title": f"CV scored {result.percentage_score}%",
                "detail": f"{result.role_profile.role_name} · {result.match_category()}",
                "link": reverse("cv_screening:screening-result-detail", args=[result.pk]),
            })
        for entry in feedback:
            detail = f"Rated {entry.rating}/5" if entry.rating else ""
            if entry.recommendation:
                detail = f"{detail} · {entry.recommendation}" if detail else entry.recommendation
            activity.append({
                "when": entry.created_at,
                "kind": "feedback",
                "title": f"Feedback from {entry.author or 'a former user'}",
                "detail": detail,
                "link": reverse("feedback-thread", args=[entry.interview_id]),
            })
        activity.sort(key=lambda event: event["when"], reverse=True)

        best_result = max(cv_results, key=lambda r: r.score, default=None)
        ratings = [entry.rating for entry in feedback if entry.rating]

        context.update({
            "can_view_applications": can_view_applications,
            "can_view_interviews": can_view_interviews,
            "can_view_feedback": can_view_feedback,
            "can_view_cv": can_view_cv,
            "applications": applications,
            "interviews": interviews,
            "next_interview": next(
                (i for i in interviews if i.status == "Scheduled" and i.scheduled_date > now), None
            ),
            "activity": activity[:12],
            "best_result": best_result,
            "best_result_coverage": _skill_coverage(best_result),
            "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
            "feedback_count": len(feedback),
        })
        return context


class CandidateCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    CreateView
):
    model = Candidate
    template_name = "candidates/candidate_form.html"

    fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "department",
        "current_status",
    ]

    permission_required = "candidates.add_candidate"
    success_url = reverse_lazy("candidate-list")
    success_message = "Candidate created successfully."
    raise_exception = True


class CandidateUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    UpdateView
):
    model = Candidate
    template_name = "candidates/candidate_form.html"

    fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "department",
        "current_status",
    ]

    permission_required = "candidates.change_candidate"
    success_url = reverse_lazy("candidate-list")
    success_message = "Candidate updated successfully."
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["application_count"] = self.object.applications.count()
        return context


class CandidateDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    DeleteView
):
    model = Candidate
    template_name = "candidates/candidate_confirm_delete.html"
    context_object_name = "candidate"

    permission_required = "candidates.delete_candidate"
    success_url = reverse_lazy("candidate-list")
    success_message = "Candidate deleted successfully."
    raise_exception = True

    def get_context_data(self, **kwargs):
        from interviews.models import Interview

        context = super().get_context_data(**kwargs)
        context["cascade"] = [
            ("application", "applications", self.object.applications.count()),
            ("interview", "interviews", Interview.objects.filter(application__candidate=self.object).count()),
        ]
        return context


# ============================================================
# APPLICATION VIEWS
# ============================================================

class ApplicationListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListToolbarMixin,
    ListView
):
    model = Application
    template_name = "candidates/application_list.html"
    context_object_name = "applications"
    paginate_by = 25

    permission_required = "candidates.view_application"
    raise_exception = True

    search_fields = ("candidate__first_name", "candidate__last_name", "candidate__email", "position__title")
    search_placeholder = "Search by candidate or position"
    sort_options = {
        "newest": ("Newest", ("-id",)),
        "oldest": ("Oldest", ("id",)),
        "candidate": ("Candidate A-Z", ("candidate__first_name", "candidate__last_name", "id")),
    }
    default_sort = "newest"

    def get_base_queryset(self):
        return Application.objects.select_related(
            "candidate", "position", "position__department"
        ).annotate(interview_count=Count("interviews", distinct=True))

    def get_tabs(self):
        return [Tab("all", "All")] + [
            Tab(key, label, Q(status__in=statuses)) for key, label, statuses in APPLICATION_TAB_GROUPS
        ]

    def apply_extra_filters(self, queryset):
        department = self.request.GET.get("dept", "").strip()
        self.active_department = department if department.isdigit() else ""
        if self.active_department:
            queryset = queryset.filter(position__department_id=self.active_department)
        return queryset

    def get_extra_toolbar_context(self):
        return {
            "departments": Department.objects.order_by("name"),
            "active_department": self.active_department,
        }


class ApplicationDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DetailView
):
    model = Application
    template_name = "candidates/application_detail.html"
    context_object_name = "application"

    permission_required = "candidates.view_application"
    raise_exception = True

    def get_queryset(self):
        return Application.objects.select_related(
            "candidate", "candidate__department", "position", "position__department", "position__screening_profile"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        application = self.object
        can_view_interviews = user.has_perm("interviews.view_interview")
        is_staff = user_in_groups(user)

        interviews = []
        if can_view_interviews:
            from interviews.models import Interview

            interviews = list(
                application.interviews.select_related("interviewer")
                .annotate(
                    feedback_count=Count("feedback_entries", filter=Q(feedback_entries__parent__isnull=True)),
                    average_rating=Avg("feedback_entries__rating", filter=Q(feedback_entries__parent__isnull=True)),
                )
                .order_by("scheduled_date")
            )

        cv_result = _latest_cv_result(application.candidate, application.position) if is_staff else None

        context.update({
            "journey": build_journey(application.status),
            "can_view_interviews": can_view_interviews,
            "interviews": interviews,
            "cv_result": cv_result,
            "cv_coverage": _skill_coverage(cv_result),
            "can_upload_cv": is_staff and application.position.screening_profile_id is not None,
            "other_applications": list(
                application.candidate.applications.exclude(pk=application.pk).select_related("position")
            ),
        })
        return context


class ApplicationCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    CreateView
):
    model = Application
    template_name = "candidates/application_form.html"

    fields = [
        "candidate",
        "position",
        "status",
    ]

    permission_required = "candidates.add_application"
    success_url = reverse_lazy("application-list")
    success_message = "Application created successfully."
    raise_exception = True


class ApplicationUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    UpdateView
):
    model = Application
    template_name = "candidates/application_form.html"

    fields = [
        "candidate",
        "position",
        "status",
    ]

    permission_required = "candidates.change_application"
    success_url = reverse_lazy("application-list")
    success_message = "Application updated successfully."
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["journey"] = build_journey(self.object.status)
        return context


class ApplicationDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    DeleteView
):
    model = Application
    template_name = "candidates/application_confirm_delete.html"
    context_object_name = "application"

    permission_required = "candidates.delete_application"
    success_url = reverse_lazy("application-list")
    success_message = "Application deleted successfully."
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cascade"] = [("interview", "interviews", self.object.interviews.count())]
        return context
