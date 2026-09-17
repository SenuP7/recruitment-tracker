"""Sending portal invites.

Goes through the same SQS/Lambda/SES path as every other candidate email
(notification_client), so there is one outgoing mail route to configure and
monitor -- see notification-service/README.md.
"""

from django.conf import settings
from django.urls import reverse

from notification_client import event_types
from notification_client.publisher import publish_event


def invite_url(request, invite):
    return request.build_absolute_uri(
        reverse("portal:accept-invite", kwargs={"token": invite.token})
    )


def send_candidate_invite(request, invite):
    """Returns whatever the publisher reports, so a failed send never breaks
    the request; the invite row still exists and can be resent."""
    candidate = invite.candidate
    return publish_event(
        event_types.PORTAL_INVITE,
        recipient_email=invite.email,
        recipient_name=candidate.full_name,
        context={
            "candidate_name": candidate.first_name or candidate.full_name,
            "company_name": settings.CANDIDFLOW_COMPANY_NAME,
            "invite_url": invite_url(request, invite),
            "expires_at": invite.expires_at.strftime("%d %b %Y, %H:%M"),
        },
    )
