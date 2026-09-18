"""Authentication events go to the audit log.

Signals rather than view code, so a sign-in is recorded however it happened --
the staff page, the candidate page, the Django admin, or a future SSO backend.
"""

from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver

from . import audit


@receiver(user_logged_in)
def _record_login(sender, request, user, **kwargs):
    audit.record(audit.LOGIN, actor=user, request=request, target=user)


@receiver(user_logged_out)
def _record_logout(sender, request, user, **kwargs):
    if user is not None:
        audit.record(audit.LOGOUT, actor=user, request=request, target=user)


@receiver(user_login_failed)
def _record_failed_login(sender, credentials, request=None, **kwargs):
    """The attempted username is recorded because that is the whole value of
    the entry -- but never the password, which Django already masks in
    `credentials`."""
    audit.record(
        audit.LOGIN_FAILED,
        request=request,
        actor_label=credentials.get("username", "") or "unknown",
        attempted_username=credentials.get("username", ""),
    )
