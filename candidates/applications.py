"""Turning a confirmed public application into pipeline data.

Kept out of the views because two things depend on getting this exactly
right: an address is only ever linked to an existing candidate record after
the person has proved they own it, and a confirmed submission must not create
a second application for a role they're already in the running for.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from notification_client import event_types
from notification_client.publisher import publish_event

from .models import Application, Candidate, CandidateInvite, PendingApplication

# Rate limits for the public form. Counted in the database rather than a
# cache, so they hold across server processes and restarts.
MAX_PER_EMAIL_PER_HOUR = 3
MAX_PER_IP_PER_HOUR = 8
RATE_LIMITED_MESSAGE = (
    "That's a lot of applications in a short time. Please wait an hour and try again, "
    "or email us if something went wrong."
)


def is_rate_limited(*, email, ip_address):
    since = timezone.now() - timedelta(hours=1)
    recent = PendingApplication.objects.filter(created_at__gte=since)
    if recent.filter(email__iexact=email).count() >= MAX_PER_EMAIL_PER_HOUR:
        return True
    if ip_address and recent.filter(ip_address=ip_address).count() >= MAX_PER_IP_PER_HOUR:
        return True
    return False


def send_application_confirmation(request, pending):
    """Emails the confirm link. Returns whatever the publisher reports; a
    failure here must not break the response, the applicant can re-apply."""
    confirm_url = request.build_absolute_uri(
        reverse("application-confirm", kwargs={"token": pending.token})
    )
    return publish_event(
        event_types.APPLICATION_CONFIRM,
        recipient_email=pending.email,
        recipient_name=pending.full_name,
        context={
            "candidate_name": pending.first_name or pending.full_name,
            "company_name": settings.CANDIDFLOW_COMPANY_NAME,
            "job_title": pending.position.title,
            "confirm_url": confirm_url,
            "expires_at": pending.expires_at.strftime("%d %b %Y, %H:%M"),
        },
    )


@dataclass
class ConfirmResult:
    candidate: Candidate
    application: Application
    created_application: bool
    invite_token: str | None
    message: str


def confirm_pending_application(pending):
    """Creates (or reuses) the candidate, the application and the CV.

    Linking to an existing candidate record only happens here, after the
    emailed link proves the address belongs to whoever clicked it.
    """
    with transaction.atomic():
        candidate, created_candidate = _candidate_for(pending)
        application, created_application = _application_for(candidate, pending)

        if created_application:
            _attach_cv(candidate, application, pending)

        pending.verified_at = timezone.now()
        pending.ip_address = None  # only ever needed for rate limiting
        pending.save(update_fields=["verified_at", "ip_address"])

        invite_token = None
        if candidate.user_id is None:
            invite_token = CandidateInvite.issue(candidate).token

    if not created_application:
        message = (
            f"You've already applied for {pending.position.title}. "
            "You can follow that application here."
        )
    elif created_candidate:
        message = "Your application is confirmed."
    else:
        message = "Your application is confirmed and added to your record."

    return ConfirmResult(
        candidate=candidate,
        application=application,
        created_application=created_application,
        invite_token=invite_token,
        message=message,
    )


def _candidate_for(pending):
    candidate = Candidate.objects.filter(email__iexact=pending.email).first()
    if candidate is not None:
        # Fill in only what's missing: a recruiter's version of a name or
        # phone number is more likely to be the corrected one.
        updates = []
        if not candidate.phone and pending.phone:
            candidate.phone = pending.phone
            updates.append("phone")
        if candidate.terms_accepted_at is None:
            candidate.terms_accepted_at = pending.terms_accepted_at
            updates.append("terms_accepted_at")
        if updates:
            candidate.save(update_fields=updates)
        return candidate, False

    return (
        Candidate.objects.create(
            first_name=pending.first_name,
            last_name=pending.last_name,
            email=pending.email,
            phone=pending.phone,
            source="public",
            terms_accepted_at=pending.terms_accepted_at,
        ),
        True,
    )


def _application_for(candidate, pending):
    """One live application per role. A closed one (rejected, withdrawn, and
    so on) doesn't block applying again later."""
    existing = (
        Application.objects.filter(candidate=candidate, position=pending.position)
        .exclude(status__in=Application.CLOSED_STATUSES)
        .order_by("-applied_at")
        .first()
    )
    if existing is not None:
        return existing, False

    return (
        Application.objects.create(
            candidate=candidate,
            position=pending.position,
            status="Applied",
            applicant_message=pending.message,
        ),
        True,
    )


def _attach_cv(candidate, application, pending):
    """Copies the held file onto a real CV record and scores it. The score
    never decides the outcome -- a recruiter confirms that (cv_screening)."""
    from cv_screening.models import CandidateCV
    from cv_screening.uploads import score_cv_safely

    cv = CandidateCV(candidate=candidate)
    pending.cv.open("rb")
    cv.file.save(pending.cv.name.rsplit("/", 1)[-1], pending.cv, save=True)

    # An unreadable CV is a recruiter's problem to look at, not a reason to
    # lose the application.
    score_cv_safely(cv, application.position.screening_profile)

    application.status = "CV Screening"
    application.save(update_fields=["status"])
    return cv


# How long after a link expires an unconfirmed application is kept. The
# privacy notice promises deletion within 30 days; changing this changes what
# that page has to say.
PENDING_RETENTION_DAYS = 30


def expired_pending_queryset(days=None):
    """Unconfirmed submissions whose link expired longer ago than the
    retention period. Confirmed ones are candidate records by now and are
    never included."""
    cutoff = timezone.now() - timedelta(days=days if days is not None else PENDING_RETENTION_DAYS)
    return PendingApplication.objects.filter(
        verified_at__isnull=True, expires_at__lt=cutoff
    ).select_related("position")


def purge_expired_pending(days=None):
    """Housekeeping: unconfirmed submissions, and the CVs attached to them,
    shouldn't sit in storage for ever. Run by
    manage.py purge_pending_applications."""
    count = 0
    for pending in expired_pending_queryset(days):
        pending.cv.delete(save=False)
        pending.delete()
        count += 1
    return count
