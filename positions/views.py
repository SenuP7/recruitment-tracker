from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Avg, Count, Q
from django.urls import reverse_lazy
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

from .models import Position


# ============================================================
# POSITION LIST
# ============================================================

class PositionListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListToolbarMixin,
    ListView
):
    model = Position
    template_name = "positions/position_list.html"
    context_object_name = "positions"
    paginate_by = 25

    permission_required = "positions.view_position"
    raise_exception = True

    search_fields = ("title", "description")
    search_placeholder = "Search positions"
    sort_options = {
        "newest": ("Newest", ("-id",)),
        "title": ("Title A-Z", ("title", "id")),
        "applicants": ("Most applicants", ("-applicant_count", "-id")),
    }
    default_sort = "newest"

    def get_base_queryset(self):
        return Position.objects.select_related("department").annotate(
            applicant_count=Count("applications", distinct=True)
        )

    def get_tabs(self):
        # Open positions stay the default and the only tab for anyone who
        # can't manage positions -- closed roles are never listed for them.
        tabs = [Tab("open", "Open", Q(is_open=True))]
        if self.request.user.has_perm("positions.change_position"):
            tabs.append(Tab("closed", "Closed", Q(is_open=False)))
        return tabs

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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Applicant bars are relative to the busiest role on the current page.
        context["max_applicants"] = max((p.applicant_count for p in context["positions"]), default=0)
        return context


# ============================================================
# POSITION DETAIL
# ============================================================

class PositionDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DetailView
):
    model = Position
    template_name = "positions/position_detail.html"
    context_object_name = "position"

    permission_required = "positions.view_position"
    raise_exception = True

    def get_queryset(self):
        """Closed roles are managers-only, matching the list: the Closed tab
        is already hidden from everyone without change_position, so leaving
        the page itself open by direct link contradicted that."""
        queryset = Position.objects.select_related("department", "screening_profile")
        if self.request.user.has_perm("positions.change_position"):
            return queryset
        return queryset.filter(is_open=True)

    def get_context_data(self, **kwargs):
        from dashboard.services import annotate_latest_cv_result, get_pipeline_counts

        context = super().get_context_data(**kwargs)
        position = self.object
        # The applicant pipeline is recruitment-internal data -- staff only,
        # regardless of which view_* permissions a group happens to hold.
        show_applicants = user_in_groups(self.request.user)

        applicants = []
        pipeline = []
        summary = None
        if show_applicants:
            applications = annotate_latest_cv_result(
                position.applications.select_related("candidate", "position")
            ).order_by("-applied_at")
            applicants = list(applications)
            pipeline = [step for step in get_pipeline_counts(applications) if step["count"]]
            scores = [a.cv_score for a in applicants if a.cv_score is not None]
            summary = {
                "total": len(applicants),
                "interviewing": sum(1 for a in applicants if a.status in ("HR Interview", "Technical Interview")),
                "accepted": sum(1 for a in applicants if a.status == "Accepted"),
                "average_score": round(sum(scores) / len(scores) * 100) if scores else None,
            }

        profile = position.screening_profile
        context.update({
            "show_applicants": show_applicants,
            "applicants": applicants,
            "pipeline": pipeline,
            "pipeline_max": max((step["count"] for step in pipeline), default=0),
            "summary": summary,
            "required_skills": list(profile.required_skills.order_by("name")) if profile else [],
            "nice_skills": list(profile.nice_to_have_skills.order_by("name")) if profile else [],
        })
        return context


# ============================================================
# CREATE POSITION
# ============================================================

class PositionCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    CreateView
):
    model = Position
    template_name = "positions/position_form.html"

    fields = [
        "title",
        "description",
        "minimum_experience",
        "is_open",
        "department",
    ]

    permission_required = "positions.add_position"
    success_url = reverse_lazy("position-list")
    success_message = "Position created successfully."
    raise_exception = True


# ============================================================
# UPDATE POSITION
# ============================================================

class PositionUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    UpdateView
):
    model = Position
    template_name = "positions/position_form.html"

    fields = [
        "title",
        "description",
        "minimum_experience",
        "is_open",
        "department",
    ]

    permission_required = "positions.change_position"
    success_url = reverse_lazy("position-list")
    success_message = "Position updated successfully."
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["applicant_count"] = self.object.applications.count()
        return context


# ============================================================
# DELETE POSITION
# ============================================================

class PositionDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    DeleteView
):
    model = Position
    template_name = "positions/position_confirm_delete.html"
    context_object_name = "position"

    permission_required = "positions.delete_position"
    success_url = reverse_lazy("position-list")
    success_message = "Position deleted successfully."
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cascade"] = [("application", "applications", self.object.applications.count())]
        return context
