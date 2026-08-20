from django.shortcuts import render
from django.views import View

from accounts.mixins import GroupRequiredMixin

from . import filters as dashboard_filters
from . import services
from .rbac import get_dashboard_scope, scoped_applications_queryset
from .services import annotate_latest_cv_result
from .utils import match_category_for_score, paginate, percentage


class DashboardAccessMixin(GroupRequiredMixin):
    """Reuses accounts.mixins.GroupRequiredMixin as-is, with one addition:
    superusers bypass the group check (they have no group memberships by
    Django convention, but should always have full dashboard access)."""

    allowed_groups = [
        "Recruiter",
        "HR Interviewer",
        "Senior Reviewer",
        "Leadership Manager",
        "Technical Interviewer",
    ]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            return super(GroupRequiredMixin, self).dispatch(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)


def build_dashboard_context(request):
    """Shared by DashboardView (full page) and DashboardResultsView (the
    HTMX partial) so the two never drift out of sync."""
    scope, department = get_dashboard_scope(request.user)

    applications = scoped_applications_queryset(request.user)
    applications = annotate_latest_cv_result(applications)
    applications = dashboard_filters.apply_filters(applications, request.GET)

    page = paginate(applications, request.GET.get("page"), per_page=25)

    rows = [
        {
            "application": application,
            "score_percent": percentage(application.cv_score),
            "match_category": match_category_for_score(application.cv_score),
        }
        for application in page.object_list
    ]

    return {
        "stats": services.get_overview_stats(request.user),
        "pipeline": services.get_pipeline_counts(request.user),
        "rows": rows,
        "page_obj": page,
        "filter_choices": dashboard_filters.get_filter_choices(),
        "active_filters": request.GET,
        "department_missing": scope == "none" and department is None,
    }


class DashboardView(DashboardAccessMixin, View):
    def get(self, request, *args, **kwargs):
        context = build_dashboard_context(request)
        return render(request, "dashboard/dashboard.html", context)


class DashboardResultsView(DashboardAccessMixin, View):
    """HTMX endpoint: returns just the results partial (stats + pipeline +
    table + pagination) so filter changes update the page without a full
    reload."""

    def get(self, request, *args, **kwargs):
        context = build_dashboard_context(request)
        return render(request, "dashboard/components/results.html", context)
