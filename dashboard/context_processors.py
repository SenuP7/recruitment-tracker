"""Exposes whether the current user can reach the dashboard, so shared
templates (the nav bar) can link to it only for users who won't get a 403 --
e.g. the Candidate group has no dashboard access, but still sees the shared
topbar on pages it IS permitted to view."""

from .views import DashboardAccessMixin


def dashboard_access(request):
    user = getattr(request, "user", None)

    if user is None or not user.is_authenticated:
        return {"can_access_dashboard": False}

    if user.is_superuser:
        return {"can_access_dashboard": True}

    allowed = set(DashboardAccessMixin.allowed_groups)
    user_groups = set(user.groups.values_list("name", flat=True))

    return {"can_access_dashboard": bool(allowed & user_groups)}
