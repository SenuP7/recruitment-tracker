"""
Dashboard business logic: statistics and pipeline calculations.

Every function here starts from rbac.scoped_applications_queryset(user) --
none of them re-derive access scope, they only aggregate over what RBAC
already allowed.
"""

from django.db.models import Count, OuterRef, Subquery

from cv_screening.models import CVMatchResult
from positions.models import Position

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


def get_overview_stats(applications):
    """The 3 top-line numbers that aren't already broken out by the
    pipeline strip (CV Screening/Passed/Failed/Accepted/Rejected all
    live there instead, to avoid showing the same count twice).

    Takes the already RBAC-scoped-and-filtered Application queryset (the
    same one the table and pipeline use) so every number on the page
    reacts to the active filters together -- nothing stays frozen while
    the table below it changes."""
    open_positions = Position.objects.filter(
        is_open=True,
        id__in=applications.values("position_id"),
    ).distinct().count()

    return {
        "total_candidates": applications.values("candidate_id").distinct().count(),
        "total_applications": applications.count(),
        "open_positions": open_positions,
    }


def get_pipeline_counts(applications):
    counts = _status_counts(applications)
    return [
        {"stage": stage, "count": counts.get(stage, 0)} for stage in PIPELINE_STAGES
    ]
