"""
Dashboard business logic: statistics and pipeline calculations.

Every function here starts from rbac.scoped_applications_queryset(user) --
none of them re-derive access scope, they only aggregate over what RBAC
already allowed.
"""

from django.db.models import Count, OuterRef, Subquery

from candidates.models import Candidate
from cv_screening.models import CVMatchResult
from positions.models import Position

from .rbac import get_dashboard_scope, scoped_applications_queryset

PIPELINE_STAGES = [
    "Applied",
    "CV Screening",
    "CV Screening Passed",
    "CV Screening Failed",
    "HR Interview",
    "Technical Interview",
    "Senior Review",
    "Accepted",
    "Rejected",
]


def annotate_latest_cv_result(queryset):
    """Attaches the CV match score/result relevant to each application --
    i.e. the result for that candidate's CV against that position's
    screening profile -- via a single correlated subquery. Avoids N+1
    entirely (one extra SELECT per row would be N+1; this is 0 extra
    queries, folded into the main SELECT)."""
    latest_result = CVMatchResult.objects.filter(
        cv__candidate=OuterRef("candidate"),
        role_profile=OuterRef("position__screening_profile"),
    ).order_by("-computed_at")

    return queryset.annotate(
        cv_score=Subquery(latest_result.values("score")[:1]),
        cv_result_id=Subquery(latest_result.values("id")[:1]),
    )


def _status_counts(queryset):
    return dict(
        queryset.values("status")
        .annotate(count=Count("id"))
        .values_list("status", "count")
    )


def get_overview_stats(user):
    """The 3 top-line numbers that aren't already broken out by the
    pipeline strip (CV Screening/Passed/Failed/Accepted/Rejected all
    live there instead, to avoid showing the same count twice)."""
    scope, department = get_dashboard_scope(user)
    applications = scoped_applications_queryset(user)

    if scope == "all":
        total_candidates = Candidate.objects.count()
        open_positions = Position.objects.filter(is_open=True).count()
    elif scope == "department":
        total_candidates = Candidate.objects.filter(department=department).count()
        open_positions = Position.objects.filter(
            is_open=True, department=department
        ).count()
    else:
        total_candidates = 0
        open_positions = 0

    return {
        "total_candidates": total_candidates,
        "total_applications": applications.count(),
        "open_positions": open_positions,
    }


def get_pipeline_counts(user):
    counts = _status_counts(scoped_applications_queryset(user))
    return [
        {"stage": stage, "count": counts.get(stage, 0)} for stage in PIPELINE_STAGES
    ]
