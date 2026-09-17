"""Live system checks behind the public Status page and the footer status dot.

Every check is cheap and local: the database gets one `SELECT 1`, while CV
storage and email notifications are configuration checks only (no network
calls to AWS), and each check says so in its detail text so the page never
claims more than it actually verified. Nothing here exposes hostnames,
bucket names, queue URLs or credentials.
"""

import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

OPERATIONAL = "operational"
DEGRADED = "degraded"
OUTAGE = "outage"
INACTIVE = "inactive"

OVERALL_LABELS = {
    OPERATIONAL: "All systems operational",
    DEGRADED: "Some systems degraded",
    OUTAGE: "Service disruption",
}

FOOTER_CACHE_KEY = "marketing:overall-status"
FOOTER_CACHE_SECONDS = 60


def _check_web():
    return {
        "name": "Web application",
        "description": "Sign-in, dashboard and every recruitment page.",
        "state": OPERATIONAL,
        "detail": f"Serving requests · v{settings.CANDIDFLOW_VERSION}",
    }


def _check_database():
    check = {
        "name": "Database",
        "description": "Candidates, applications, interviews and feedback.",
    }
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        check.update(state=OUTAGE, detail="Not reachable")
        return check
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    check.update(state=OPERATIONAL, detail=f"Reachable · {elapsed_ms} ms")
    return check


def _check_cv_storage():
    check = {
        "name": "CV storage",
        "description": "Uploading, scoring and opening candidate CVs.",
    }
    backend = settings.STORAGES.get("default", {}).get("BACKEND", "")
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
    if backend.endswith("S3Boto3Storage") and bucket:
        check.update(state=OPERATIONAL, detail="Configured · not probed live")
    else:
        check.update(state=DEGRADED, detail="Storage is not configured")
    return check


def _check_notifications():
    check = {
        "name": "Email notifications",
        "description": "Status-change and interview emails to candidates.",
    }
    if settings.NOTIFICATIONS_LOCAL_MODE:
        check.update(state=INACTIVE, detail="Local mode · emails are written to files, not sent")
    elif settings.NOTIFICATIONS_SQS_QUEUE_URL:
        check.update(state=OPERATIONAL, detail="Configured · delivery queue connected")
    else:
        check.update(state=INACTIVE, detail="Turned off in this environment")
    return check


def overall_state(checks):
    """The web app and database decide an outage; anything else only degrades.
    INACTIVE (deliberately switched off) never counts against the status."""
    states = {check["name"]: check["state"] for check in checks}
    if states.get("Web application") == OUTAGE or states.get("Database") == OUTAGE:
        return OUTAGE
    if any(state in (OUTAGE, DEGRADED) for state in states.values()):
        return DEGRADED
    return OPERATIONAL


def run_checks():
    checks = [_check_web(), _check_database(), _check_cv_storage(), _check_notifications()]
    state = overall_state(checks)
    result = {
        "checks": checks,
        "state": state,
        "label": OVERALL_LABELS[state],
        "checked_at": timezone.now(),
    }
    cache.set(FOOTER_CACHE_KEY, {"state": state, "label": result["label"]}, FOOTER_CACHE_SECONDS)
    return result


def footer_status():
    """Cached summary for the footer on every public page, so browsing the
    legal pages doesn't run a database check per request."""
    summary = cache.get(FOOTER_CACHE_KEY)
    if summary is None:
        summary = {key: run_checks()[key] for key in ("state", "label")}
    return summary
