"""Exposes whether the current user can reach recruitment-staff-only areas
(the dashboard, CV screening), so shared templates (the nav bar) only link
to them for users who won't get a 403 -- e.g. the Candidate group has
access to neither, but still sees the shared topbar on pages it IS
permitted to view.

Both flags are computed from the same accounts.decorators.RECRUITMENT_STAFF_GROUPS
that actually gates DashboardAccessMixin and cv_screening's @group_required
views, so the nav can never show a link the user would then get denied on."""

from accounts.decorators import user_in_groups
from accounts.staff import is_administrator


AUDIT_VIEWER_GROUPS = ("Leadership Manager", "Administrator")


def dashboard_access(request):
    user = getattr(request, "user", None)
    allowed = user is not None and user_in_groups(user)

    return {
        "can_access_dashboard": allowed,
        "can_access_cv_screening": allowed,
        # Same check the view enforces (accounts.views.AuditLogView), so the
        # link can never appear for someone who would then get a 403.
        "can_view_audit_log": user is not None and user_in_groups(user, AUDIT_VIEWER_GROUPS),
        # Same check accounts.staff_views.AdministratorRequiredMixin enforces.
        "can_manage_staff": user is not None and is_administrator(user),
    }
