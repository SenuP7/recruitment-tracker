from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Current querystring with the given keys replaced (or removed when the
    value is empty), so pagination links keep the active tab/search/sort
    and tab links drop the stale page number."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.filter
def initials(value):
    """'Alice Wonder' -> 'AW'; falls back to the first two characters."""
    text = str(value or "").strip()
    if not text:
        return "?"
    parts = text.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return text[:2].upper()


@register.filter
def percent_of(value, total):
    """Integer percentage of value against total, clamped to 0-100, used for
    bar widths. Returns 0 rather than failing on a zero or missing total."""
    try:
        value = float(value or 0)
        total = float(total or 0)
    except (TypeError, ValueError):
        return 0
    if total <= 0:
        return 0
    return max(0, min(100, round(value / total * 100)))


@register.filter
def nonzero(items):
    """Keeps only (…, count) tuples whose final count is non-zero."""
    return [item for item in (items or []) if item[-1]]


@register.filter
def score_pct(score):
    """CVMatchResult scores are stored 0.0-1.0."""
    if score is None:
        return None
    return round(float(score) * 100)
