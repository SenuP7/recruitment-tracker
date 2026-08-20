"""
Function-view equivalent of accounts.mixins.GroupRequiredMixin.

Same semantics (check request.user.groups against an allowed list, deny
otherwise), just usable as a decorator for the function-based views in
cv_screening/views.py rather than the class-based views the mixin was
built for. Not a second permission system -- same group names, same
"deny unless in an allowed group" rule, just adapted to FBVs.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

# The groups with legitimate access to recruitment-internal data (CV
# screening, the dashboard). The Candidate group is deliberately excluded --
# candidates are the subject of this data, not reviewers of it, and there is
# no mechanism in this app linking a Candidate-group login to a specific
# Candidate record, so there's no "view your own CV" case to carve out.
RECRUITMENT_STAFF_GROUPS = (
    "Recruiter",
    "HR Interviewer",
    "Senior Reviewer",
    "Leadership Manager",
    "Technical Interviewer",
)


def user_in_groups(user, group_names=RECRUITMENT_STAFF_GROUPS):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


def group_required(*group_names):
    """Usage: @group_required("Recruiter", "HR Interviewer")
    Implies login_required -- an anonymous user is redirected to login
    same as any other @login_required view, not denied outright."""

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not user_in_groups(request.user, group_names):
                raise PermissionDenied(
                    "You do not have permission to access this page."
                )
            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator
