"""Small dashboard helper functions."""

# Same thresholds as CVMatchResult.match_category() in cv_screening/models.py.
MATCH_CATEGORY_RANGES = {
    "excellent": (0.8, None),
    "good": (0.6, 0.8),
    "needs_review": (0.4, 0.6),
    "poor": (None, 0.4),
}

MATCH_CATEGORY_LABELS = {
    "excellent": "Excellent Match",
    "good": "Good Match",
    "needs_review": "Needs Review",
    "poor": "Poor Match",
}


def match_category_for_score(score):
    """Mirrors CVMatchResult.match_category() for a bare score value,
    for rows where we only have the annotated cv_score float rather
    than a full CVMatchResult instance."""
    if score is None:
        return None
    if score >= 0.8:
        return "Excellent Match"
    if score >= 0.6:
        return "Good Match"
    if score >= 0.4:
        return "Needs Review"
    return "Poor Match"


def percentage(score):
    if score is None:
        return None
    return round(score * 100)


def paginate(queryset, page_number, per_page=25):
    from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

    paginator = Paginator(queryset, per_page)
    try:
        return paginator.page(page_number)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)
