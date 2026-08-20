"""
Dashboard filter application.

These filters ONLY narrow a queryset that has already been through
rbac.scoped_applications_queryset() -- they never widen it, and never
run against an unscoped queryset. All values are read from GET params
and validated defensively; nothing here trusts the frontend.

Note: the spec's "Application Stage" and "Application Status" are the
same underlying field in this data model (Application.status, using the
existing 9-stage STATUS_CHOICES) -- there is no separate stage field, so
both are served by the single `status` filter below.
"""

from django.db.models import Q

from candidates.models import Application
from positions.models import Position

from .utils import MATCH_CATEGORY_LABELS, MATCH_CATEGORY_RANGES


def _parse_percent(raw):
    """Score filter inputs arrive as whole percentages (e.g. "70");
    CVMatchResult.score is stored as a 0.0-1.0 float."""
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, value)) / 100


def apply_filters(queryset, params):
    department = params.get("department", "").strip()
    if department.isdigit():
        queryset = queryset.filter(candidate__department_id=department)

    position = params.get("position", "").strip()
    if position.isdigit():
        queryset = queryset.filter(position_id=position)

    status = params.get("status", "").strip()
    valid_statuses = {choice[0] for choice in Application.STATUS_CHOICES}
    if status in valid_statuses:
        queryset = queryset.filter(status=status)

    search = params.get("search", "").strip()
    if search:
        # Match each word against first/last name/email independently (AND
        # across words, OR across fields per word) so a full-name search
        # like "Jane Doe" matches first_name="Jane" + last_name="Doe" even
        # though neither field alone contains the full query string.
        for term in search.split():
            queryset = queryset.filter(
                Q(candidate__first_name__icontains=term)
                | Q(candidate__last_name__icontains=term)
                | Q(candidate__email__icontains=term)
            )

    score_min = _parse_percent(params.get("score_min"))
    if score_min is not None:
        queryset = queryset.filter(cv_score__gte=score_min)

    score_max = _parse_percent(params.get("score_max"))
    if score_max is not None:
        queryset = queryset.filter(cv_score__lte=score_max)

    category = params.get("category", "").strip()
    if category in MATCH_CATEGORY_RANGES:
        low, high = MATCH_CATEGORY_RANGES[category]
        if low is not None:
            queryset = queryset.filter(cv_score__gte=low)
        if high is not None:
            queryset = queryset.filter(cv_score__lt=high)

    return queryset.order_by("-applied_at")


def get_filter_choices():
    """Department/Position/Status choices for populating the filter form.
    Selecting a value outside the user's RBAC scope simply yields zero
    results -- it can never widen what apply_filters() returns, since
    filtering always runs on top of the already-scoped queryset."""
    from accounts.models import Department

    return {
        "departments": Department.objects.order_by("name"),
        "positions": Position.objects.select_related("department").order_by("title"),
        "statuses": Application.STATUS_CHOICES,
        "categories": list(MATCH_CATEGORY_LABELS.items()),
    }
