import csv
import itertools

from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from accounts.decorators import RECRUITMENT_STAFF_GROUPS
from accounts.mixins import GroupRequiredMixin

from . import filters as dashboard_filters
from . import services
from .rbac import get_dashboard_scope, scoped_applications_queryset
from .services import annotate_latest_cv_result
from .utils import match_category_for_score, paginate, percentage


class DashboardAccessMixin(GroupRequiredMixin):
    """Reuses accounts.mixins.GroupRequiredMixin as-is, with one addition:
    superusers bypass the group check (they have no group memberships by
    Django convention, but should always have full dashboard access).

    Same allowed-group list as cv_screening's @group_required -- both are
    "recruitment staff only" gates, sourced from one shared constant so
    they can't drift apart."""

    allowed_groups = list(RECRUITMENT_STAFF_GROUPS)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            return super(GroupRequiredMixin, self).dispatch(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)


def build_attention_rail(user, scoped_applications):
    """Upcoming interviews and recent feedback for the 'Needs attention'
    rail. Deliberately built from the RBAC-scoped queryset *before* filters
    are applied: the rail is about what's coming up across the user's whole
    scope, not a reflection of whatever the table is filtered to."""
    from interviews.models import Interview, InterviewFeedback, StaffNotification

    now = timezone.now()
    in_scope = Q(application__in=scoped_applications.values("pk"))

    upcoming = list(
        Interview.objects.filter(in_scope, status="Scheduled", scheduled_date__gte=now)
        .select_related("application__candidate", "application__position", "assigned_interviewer")
        .order_by("scheduled_date")[:5]
    )
    overdue_count = Interview.objects.filter(in_scope, status="Scheduled", scheduled_date__lt=now).count()

    recent_feedback = []
    if user.has_perm("interviews.view_interviewfeedback"):
        recent_feedback = list(
            InterviewFeedback.objects.filter(
                interview__application__in=scoped_applications.values("pk"), parent__isnull=True
            )
            .select_related("author", "interview__application__candidate")
            .order_by("-created_at")[:4]
        )

    notifications = list(StaffNotification.objects.filter(recipient=user, is_read=False).order_by("-created_at")[:3])

    return {
        "upcoming_interviews": upcoming,
        "overdue_count": overdue_count,
        "recent_feedback": recent_feedback,
        "rail_notifications": notifications,
    }


def greeting_for(moment):
    hour = timezone.localtime(moment).hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def build_dashboard_context(request):
    """Shared by DashboardView (full page) and DashboardResultsView (the
    HTMX partial) so the two never drift out of sync."""
    scope, department = get_dashboard_scope(request.user)

    scoped = scoped_applications_queryset(request.user)
    applications = annotate_latest_cv_result(scoped)
    applications = dashboard_filters.apply_filters(applications, request.GET)

    # Stats and pipeline are computed from this same RBAC-scoped-and-filtered
    # queryset as the table below, so every number on the page reacts to the
    # active filters together instead of the overview staying frozen.
    stats = services.get_overview_stats(applications)
    pipeline = services.get_pipeline_counts(applications)

    page = paginate(applications, request.GET.get("page"), per_page=25)

    rows = [
        {
            "application": application,
            "score_percent": percentage(application.cv_score),
            "match_category": match_category_for_score(application.cv_score),
        }
        for application in page.object_list
    ]

    active_filter_count = sum(
        1 for key in ("search", "department", "position", "status", "category", "score_min", "score_max")
        if request.GET.get(key, "").strip()
    )

    return {
        "stats": stats,
        "pipeline": pipeline,
        "pipeline_max": max((step["count"] for step in pipeline), default=0),
        "rows": rows,
        "page_obj": page,
        "filter_choices": dashboard_filters.get_filter_choices(),
        "active_filters": request.GET,
        "active_filter_count": active_filter_count,
        "department_missing": scope == "none" and department is None,
    }


class DashboardView(DashboardAccessMixin, View):
    def get(self, request, *args, **kwargs):
        context = build_dashboard_context(request)
        context["greeting"] = greeting_for(timezone.now())
        context.update(build_attention_rail(request.user, scoped_applications_queryset(request.user)))
        return render(request, "dashboard/dashboard.html", context)


class DashboardResultsView(DashboardAccessMixin, View):
    """HTMX endpoint: returns just the results partial (stats + pipeline +
    table + pagination) so filter changes update the page without a full
    reload."""

    def get(self, request, *args, **kwargs):
        context = build_dashboard_context(request)
        return render(request, "dashboard/components/results.html", context)


class _Echo:
    """Django's documented pattern for streaming CSV: a write-only, no-op
    "file" whose write() just returns the value unchanged, so csv.writer
    can be driven by a generator instead of buffering the whole file in
    memory before sending anything."""

    def write(self, value):
        return value


CSV_HEADER = [
    "Candidate Name", "Email", "Department", "Position", "Status",
    "CV Score (%)", "Match Category", "Applied Date",
]


def _application_csv_row(application):
    candidate = application.candidate
    return [
        f"{candidate.first_name} {candidate.last_name}",
        candidate.email,
        candidate.department.name if candidate.department else "",
        application.position.title,
        application.status,
        percentage(application.cv_score) if application.cv_score is not None else "",
        match_category_for_score(application.cv_score) or "",
        application.applied_at.strftime("%Y-%m-%d"),
    ]


class DashboardExportView(DashboardAccessMixin, View):
    """CSV export of exactly what the dashboard table would show for this
    request -- same RBAC scope (scoped_applications_queryset), same active
    filters (dashboard_filters.apply_filters reads the same request.GET),
    just unpaginated (every matching row, not one page of 25) and streamed
    rather than buffered, so large exports don't sit in memory first."""

    def get(self, request, *args, **kwargs):
        applications = scoped_applications_queryset(request.user)
        applications = annotate_latest_cv_result(applications)
        applications = dashboard_filters.apply_filters(applications, request.GET)

        writer = csv.writer(_Echo())
        all_rows = itertools.chain(
            [CSV_HEADER],
            (_application_csv_row(application) for application in applications),
        )
        streamed_rows = (writer.writerow(row) for row in all_rows)

        response = StreamingHttpResponse(streamed_rows, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="recruitment_pipeline.csv"'
        return response
