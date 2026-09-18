"""Who did what, and when.

One append-only table for the whole application. `FeedbackAuditLog` stays as
it is -- it records before/after values for one specific model and predates
this -- but everything else (sign-in, candidate and interview changes, role
changes, delegation) is recorded here.

Two design rules worth keeping:

* **Labels are snapshots.** `actor_label` and `target_label` are copied in at
  the time of the event, so a log entry still reads sensibly after the user
  or the record it refers to has been deleted.
* **Rows are immutable.** `AuditEvent.save()` refuses to update an existing
  row, so a log that an administrator can quietly edit -- which proves
  nothing -- isn't possible through the ORM.
"""

import logging

logger = logging.getLogger(__name__)

# Longer than the 12 months candidate records are kept, so "who deleted this"
# can still be answered after the record itself is gone. Enforced by
# manage.py purge_audit_events.
AUDIT_RETENTION_DAYS = 730

# Authentication
LOGIN = "auth.login"
LOGOUT = "auth.logout"
LOGIN_FAILED = "auth.login_failed"
LOGIN_BLOCKED = "auth.login_blocked"
PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"
PASSWORD_CHANGED = "auth.password_changed"

# Staff administration
STAFF_CREATED = "staff.created"
STAFF_DEACTIVATED = "staff.deactivated"
STAFF_REACTIVATED = "staff.reactivated"
ROLE_ASSIGNED = "staff.role_assigned"
ROLE_REMOVED = "staff.role_removed"
SESSIONS_REVOKED = "staff.sessions_revoked"

# Recruitment records
CANDIDATE_CREATED = "candidate.created"
CANDIDATE_UPDATED = "candidate.updated"
CANDIDATE_DELETED = "candidate.deleted"
CANDIDATE_INVITED = "candidate.invited"
CV_UPLOADED = "candidate.cv_uploaded"
APPLICATION_CREATED = "application.created"
APPLICATION_STATUS_CHANGED = "application.status_changed"
APPLICATION_WITHDRAWN = "application.withdrawn"
SCREENING_DECIDED = "application.screening_decided"

# Interviews and delegation
INTERVIEW_CREATED = "interview.created"
INTERVIEW_UPDATED = "interview.updated"
INTERVIEW_CANCELLED = "interview.cancelled"
INTERVIEW_COMPLETED = "interview.completed"
INTERVIEWER_ASSIGNED = "interview.interviewer_assigned"
DELEGATION_OFFERED = "delegation.offered"
DELEGATION_ACCEPTED = "delegation.accepted"
DELEGATION_DECLINED = "delegation.declined"
DELEGATION_WITHDRAWN = "delegation.withdrawn"
DELEGATION_EXPIRED = "delegation.expired"

# Shown on the audit page; anything not listed still records fine.
ACTION_LABELS = {
    LOGIN: "Signed in",
    LOGOUT: "Signed out",
    LOGIN_FAILED: "Failed sign-in",
    LOGIN_BLOCKED: "Sign-in blocked (too many attempts)",
    PASSWORD_RESET_REQUESTED: "Requested a password reset",
    PASSWORD_CHANGED: "Changed a password",
    STAFF_CREATED: "Created a staff account",
    STAFF_DEACTIVATED: "Deactivated a staff account",
    STAFF_REACTIVATED: "Reactivated a staff account",
    ROLE_ASSIGNED: "Assigned a role",
    ROLE_REMOVED: "Removed a role",
    SESSIONS_REVOKED: "Signed out all sessions",
    CANDIDATE_CREATED: "Created a candidate",
    CANDIDATE_UPDATED: "Updated a candidate",
    CANDIDATE_DELETED: "Deleted a candidate",
    CANDIDATE_INVITED: "Invited a candidate to the portal",
    CV_UPLOADED: "Uploaded a CV",
    APPLICATION_CREATED: "Created an application",
    APPLICATION_STATUS_CHANGED: "Changed an application's stage",
    APPLICATION_WITHDRAWN: "Withdrew an application",
    SCREENING_DECIDED: "Recorded a screening outcome",
    INTERVIEW_CREATED: "Scheduled an interview",
    INTERVIEW_UPDATED: "Updated an interview",
    INTERVIEW_CANCELLED: "Cancelled an interview",
    INTERVIEW_COMPLETED: "Completed an interview",
    INTERVIEWER_ASSIGNED: "Assigned an interviewer",
    DELEGATION_OFFERED: "Offered a delegation",
    DELEGATION_ACCEPTED: "Accepted a delegation",
    DELEGATION_DECLINED: "Declined a delegation",
    DELEGATION_WITHDRAWN: "Withdrew a delegation",
    DELEGATION_EXPIRED: "Delegation expired",
}

AUTHENTICATION_ACTIONS = {
    LOGIN, LOGOUT, LOGIN_FAILED, LOGIN_BLOCKED,
    PASSWORD_RESET_REQUESTED, PASSWORD_CHANGED,
}


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record(action, *, actor=None, request=None, target=None, actor_label="", **detail):
    """Writes one audit entry.

    Never raises: an audit failure must not roll back the action it was
    describing, or a full log table would take the site down. A failure is
    logged loudly instead.

    IP and user agent are only kept for authentication events -- they are
    personal data, and knowing where a sign-in came from is useful in a way
    that knowing where a candidate edit came from is not.
    """
    from .models import AuditEvent

    try:
        if actor is None and request is not None:
            user = getattr(request, "user", None)
            actor = user if (user is not None and user.is_authenticated) else None

        keep_device = action in AUTHENTICATION_ACTIONS

        return AuditEvent.objects.create(
            actor=actor,
            actor_label=actor_label or (actor.get_username() if actor else "anonymous"),
            action=action,
            target_type=target._meta.model_name if target is not None else "",
            target_id=str(target.pk) if getattr(target, "pk", None) else "",
            target_label=str(target)[:200] if target is not None else "",
            detail=detail or {},
            ip_address=client_ip(request) if keep_device else None,
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if keep_device and request else ""),
        )
    except Exception as error:
        logger.error("Could not write audit event %s: %s", action, error)
        return None
