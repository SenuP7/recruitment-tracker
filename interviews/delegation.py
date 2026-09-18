"""Delegating an interview to someone else.

The rules, all decided with the user:

* only the assigned interviewer, a department chief over that department, or
  an administrator may delegate a round;
* the delegate must accept before responsibility moves -- until then the
  assigned interviewer still owns it;
* one hop only: a delegate cannot pass it on again, because a chain makes
  "who is actually turning up" unanswerable;
* declining needs a reason, and the person who asked is told;
* a pending offer expires shortly before the interview and reverts, rather
  than leaving an interview nobody has agreed to run;
* every step is audited, and none of it is visible to the candidate.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts import audit
from accounts.decorators import RECRUITMENT_STAFF_GROUPS, user_in_groups
from accounts.staff import ADMIN_GROUP, DEPARTMENT_CHIEF_GROUP, is_administrator

from .models import Interview, InterviewDelegation, StaffNotification

logger = logging.getLogger(__name__)

# A pending offer this close to the interview is no use to anybody: it
# reverts so the assigned interviewer knows the round is theirs again.
PENDING_EXPIRY_HOURS = 48


def eligible_delegates(interview, *, exclude_user=None):
    """Who may be offered this round.

    Any active member of staff who could interview, which includes department
    chiefs. Candidates are excluded by construction -- they hold none of these
    roles. Chiefs of the position's department are listed first, since they
    are the usual answer, but nobody is hidden: cover often crosses teams.
    """
    from django.contrib.auth.models import User

    roles = tuple(RECRUITMENT_STAFF_GROUPS) + (DEPARTMENT_CHIEF_GROUP, ADMIN_GROUP)
    people = (
        User.objects.filter(is_active=True, groups__name__in=roles)
        .exclude(pk=getattr(exclude_user, "pk", None))
        .distinct()
    )

    department = getattr(interview.application.position, "department", None)
    chief_ids = set()
    if department is not None:
        chief_ids = set(department.chiefs.values_list("id", flat=True))

    return sorted(
        people,
        key=lambda user: (user.pk not in chief_ids, (user.get_full_name() or user.username).lower()),
    )


def can_delegate(user, interview):
    """Who may hand this round to someone else."""
    if not user.is_authenticated or not user.is_active:
        return False
    if is_administrator(user):
        return True
    if interview.assigned_interviewer_id == user.pk:
        return True

    # A chief may arrange cover within their own department.
    department = getattr(interview.application.position, "department", None)
    if department is not None and department.chiefs.filter(pk=user.pk).exists():
        return True
    return False


def can_respond(user, delegation):
    """Only the person actually asked can accept or decline."""
    return delegation.status == InterviewDelegation.PENDING and delegation.to_user_id == user.pk


def _notify(recipient, message, interview):
    if recipient is None:
        return
    StaffNotification.objects.create(
        recipient=recipient,
        message=message,
        link=reverse("interview-detail", kwargs={"pk": interview.pk}),
    )


@transaction.atomic
def offer(interview, *, to_user, reason, actor, request=None):
    """Offers the round to someone. Replaces any offer still outstanding, so
    there is never more than one live delegation per interview."""
    InterviewDelegation.objects.filter(
        interview=interview, status=InterviewDelegation.PENDING
    ).update(status=InterviewDelegation.WITHDRAWN, closed_at=timezone.now())

    delegation = InterviewDelegation.objects.create(
        interview=interview,
        from_user=actor,
        to_user=to_user,
        reason=reason,
    )

    audit.record(
        audit.DELEGATION_OFFERED,
        actor=actor,
        request=request,
        target=interview,
        to=to_user.get_username(),
        reason=reason,
        crosses_departments=delegation.crosses_departments,
    )
    _notify(
        to_user,
        f"{actor.get_full_name() or actor.get_username()} asked you to conduct the "
        f"{interview.interview_type} interview for {interview.application.candidate}.",
        interview,
    )
    return delegation


@transaction.atomic
def accept(delegation, *, actor, request=None, note=""):
    delegation.status = InterviewDelegation.ACCEPTED
    delegation.responded_at = timezone.now()
    delegation.response_note = note
    delegation.save(update_fields=["status", "responded_at", "response_note"])

    audit.record(
        audit.DELEGATION_ACCEPTED,
        actor=actor,
        request=request,
        target=delegation.interview,
        from_user=delegation.from_user.get_username() if delegation.from_user else "",
    )
    _notify(
        delegation.from_user,
        f"{actor.get_full_name() or actor.get_username()} accepted the "
        f"{delegation.interview.interview_type} interview for {delegation.interview.application.candidate}.",
        delegation.interview,
    )
    return delegation


@transaction.atomic
def decline(delegation, *, actor, request=None, note=""):
    """Declining returns the round to whoever was assigned it. Nothing about
    the interview changes -- it was never theirs to begin with."""
    delegation.status = InterviewDelegation.DECLINED
    delegation.responded_at = timezone.now()
    delegation.closed_at = timezone.now()
    delegation.response_note = note
    delegation.save(update_fields=["status", "responded_at", "closed_at", "response_note"])

    audit.record(
        audit.DELEGATION_DECLINED,
        actor=actor,
        request=request,
        target=delegation.interview,
        note=note,
    )
    _notify(
        delegation.from_user,
        f"{actor.get_full_name() or actor.get_username()} can't take the "
        f"{delegation.interview.interview_type} interview for "
        f"{delegation.interview.application.candidate}. It's back with you."
        + (f" They said: {note}" if note else ""),
        delegation.interview,
    )
    return delegation


@transaction.atomic
def withdraw(delegation, *, actor, request=None):
    """The person who asked (or an administrator) taking it back."""
    delegation.status = InterviewDelegation.WITHDRAWN
    delegation.closed_at = timezone.now()
    delegation.save(update_fields=["status", "closed_at"])

    audit.record(
        audit.DELEGATION_WITHDRAWN, actor=actor, request=request, target=delegation.interview
    )
    _notify(
        delegation.to_user,
        f"The {delegation.interview.interview_type} interview for "
        f"{delegation.interview.application.candidate} is no longer with you.",
        delegation.interview,
    )
    return delegation


def close_for_interview(interview, *, actor=None, request=None):
    """Called when an interview is cancelled or completed: an open delegation
    on a round that is over is just noise in someone's list."""
    open_ones = list(interview.delegations.filter(status__in=InterviewDelegation.OPEN_STATUSES))
    for delegation in open_ones:
        delegation.status = InterviewDelegation.WITHDRAWN
        delegation.closed_at = timezone.now()
        delegation.save(update_fields=["status", "closed_at"])
        audit.record(
            audit.DELEGATION_WITHDRAWN,
            actor=actor,
            request=request,
            target=interview,
            reason=f"interview {interview.status.lower()}",
        )
    return len(open_ones)


def expire_stale_offers(hours=PENDING_EXPIRY_HOURS):
    """Reverts pending offers that are too close to the interview to be any
    use. Run by manage.py expire_delegations."""
    cutoff = timezone.now() + timedelta(hours=hours)
    stale = InterviewDelegation.objects.filter(
        status=InterviewDelegation.PENDING,
        interview__scheduled_date__lte=cutoff,
        interview__status="Scheduled",
    ).select_related("interview", "from_user", "to_user")

    expired = 0
    for delegation in stale:
        delegation.status = InterviewDelegation.EXPIRED
        delegation.closed_at = timezone.now()
        delegation.save(update_fields=["status", "closed_at"])

        audit.record(
            audit.DELEGATION_EXPIRED,
            actor=None,
            target=delegation.interview,
            to=delegation.to_user.get_username(),
            hours_before=hours,
        )
        _notify(
            delegation.from_user,
            f"Nobody answered your request to cover the {delegation.interview.interview_type} "
            f"interview for {delegation.interview.application.candidate}. It's back with you.",
            delegation.interview,
        )
        expired += 1

    return expired
