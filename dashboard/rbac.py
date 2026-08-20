"""
Dashboard RBAC boundary.

This is the ONLY place that decides which Application rows a user is
allowed to see. services.py and filters.py both build on top of the
queryset returned here and never re-derive scope themselves -- filters
narrow this queryset further, they never widen it.

Reuses the existing accounts.mixins group-based approach (see
DashboardAccessMixin in views.py, which subclasses
accounts.mixins.GroupRequiredMixin) and the existing UserProfile
department lookup pattern from accounts.mixins.DepartmentRequiredMixin,
without inheriting that mixin's dispatch-time PermissionDenied behavior --
the dashboard needs a graceful empty-state for a missing department
instead of a hard 403, per the error-handling requirements.
"""

from django.core.exceptions import ObjectDoesNotExist

from candidates.models import Application

# Groups with system-wide / broad recruitment visibility -- no department
# scoping applied.
BROAD_GROUPS = {
    "Recruiter",
    "HR Interviewer",
    "Senior Reviewer",
    "Leadership Manager",
}

# Groups restricted to their own department's data.
DEPARTMENT_SCOPED_GROUPS = {
    "Technical Interviewer",
}

# Every other group (e.g. "Candidate") -- and anyone in no recognized
# group -- gets no dashboard access at all. This is enforced at the view
# layer by DashboardAccessMixin.allowed_groups; rbac.py additionally
# fails closed (returns .none()) if it's ever reached by such a user.


def get_user_department(user):
    """Same lookup as DepartmentRequiredMixin.get_user_department(), but
    also catches a missing UserProfile row (ObjectDoesNotExist), which
    the existing mixin's `except AttributeError` does not."""
    try:
        return user.profile.department
    except (AttributeError, ObjectDoesNotExist):
        return None


def get_dashboard_scope(user):
    """Returns ('all', None), ('department', Department), or ('none', None)."""
    if not user.is_authenticated:
        return ("none", None)

    if user.is_superuser:
        return ("all", None)

    user_groups = set(user.groups.values_list("name", flat=True))

    if user_groups & BROAD_GROUPS:
        return ("all", None)

    if user_groups & DEPARTMENT_SCOPED_GROUPS:
        department = get_user_department(user)
        if department is None:
            return ("none", None)
        return ("department", department)

    return ("none", None)


def scoped_applications_queryset(user):
    """The one queryset every dashboard view/service/filter starts from.
    Security happens here, at the queryset level -- never in the template."""
    scope, department = get_dashboard_scope(user)

    base = Application.objects.select_related(
        "candidate",
        "candidate__department",
        "position",
        "position__department",
        "position__screening_profile",
    )

    if scope == "all":
        return base

    if scope == "department":
        return base.filter(candidate__department=department)

    return base.none()
