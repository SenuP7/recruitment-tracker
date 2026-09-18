"""Staff account administration.

The rules this enforces, all of which you asked for:

* every staff member has their own account -- nothing here creates a shared
  one, and the username is the person's work email;
* an administrator creates the account but never learns the password: the
  account starts unusable and the person sets their own via an emailed link;
* leavers are deactivated, not deleted, so their feedback and audit trail
  survive;
* deactivating one person never affects anyone else who holds the same role.

Deactivation takes effect immediately, including on sessions that are already
signed in: Django's ModelBackend re-checks `is_active` when it loads the user
for each request, so an existing session stops working on its next click.
`revoke_sessions` additionally clears the session rows, which is what "sign
out everywhere" does.
"""

import logging

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.sessions.models import Session
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from notification_client import event_types
from notification_client.publisher import publish_event

from . import audit
from .decorators import RECRUITMENT_STAFF_GROUPS
from .models import StaffInvite, UserProfile

logger = logging.getLogger(__name__)

ADMIN_GROUP = "Administrator"
DEPARTMENT_CHIEF_GROUP = "Department Chief"

# Every role a staff account can hold. Candidates are deliberately absent:
# a person is either staff or a candidate, never both.
ASSIGNABLE_ROLES = tuple(RECRUITMENT_STAFF_GROUPS) + (DEPARTMENT_CHIEF_GROUP, ADMIN_GROUP)

# Staff see everyone's data, so their sessions are much shorter than a
# candidate's. Rolling, because SESSION_SAVE_EVERY_REQUEST makes each request
# push the expiry out -- so this is idle time, not total time signed in.
STAFF_SESSION_SECONDS = 8 * 60 * 60


def is_administrator(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=ADMIN_GROUP).exists()
    )


def staff_queryset():
    """Everyone with a staff role, plus superusers. Deactivated accounts are
    included -- an administrator needs to see who has been switched off."""
    return (
        User.objects.filter(groups__name__in=ASSIGNABLE_ROLES)
        .distinct()
        .select_related("profile", "profile__department")
        .prefetch_related("groups")
        .order_by("-is_active", "username")
    )


@transaction.atomic
def create_staff_account(*, email, first_name, last_name, roles, department=None, job_title="", created_by=None, request=None):
    """Creates one account and returns (user, invite).

    The password is left unusable: nobody, including the administrator who
    created the account, can sign in as this person until they set their own.
    """
    email = email.strip().lower()
    user = User.objects.create(
        username=email,
        email=email,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        is_active=True,
    )
    user.set_unusable_password()
    user.save()

    for role in roles:
        user.groups.add(Group.objects.get_or_create(name=role)[0])

    UserProfile.objects.update_or_create(
        user=user,
        defaults={"department": department, "job_title": job_title, "must_change_password": True},
    )

    invite = StaffInvite.issue(user, created_by=created_by)

    audit.record(
        audit.STAFF_CREATED,
        actor=created_by,
        request=request,
        target=user,
        roles=list(roles),
        department=department.name if department else None,
    )
    return user, invite


def send_staff_invite(request, invite):
    """Goes through the same notification pipeline as every other email."""
    user = invite.user
    return publish_event(
        event_types.STAFF_INVITE,
        recipient_email=invite.email,
        recipient_name=user.get_full_name() or user.get_username(),
        context={
            "recipient_name": user.first_name or user.get_username(),
            "company_name": settings.CANDIDFLOW_COMPANY_NAME,
            "setup_url": request.build_absolute_uri(
                reverse("staff-accept-invite", kwargs={"token": invite.token})
            ),
            "expires_at": invite.expires_at.strftime("%d %b %Y, %H:%M"),
        },
    )


def revoke_sessions(user, *, actor=None, request=None, reason=""):
    """Ends every signed-in session for this user.

    Sessions are opaque rows, so each one has to be decoded to find whose it
    is. The table is small (staff plus candidates), and this only runs on
    deactivation or an explicit "sign out everywhere".
    """
    removed = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        try:
            data = session.get_decoded()
        except Exception:
            continue
        if str(data.get("_auth_user_id", "")) == str(user.pk):
            session.delete()
            removed += 1

    if removed:
        audit.record(
            audit.SESSIONS_REVOKED,
            actor=actor or user,
            request=request,
            target=user,
            sessions=removed,
            reason=reason or "",
        )
    return removed


@transaction.atomic
def deactivate_staff(user, *, actor, request=None, reason=""):
    """Blocks sign-in and ends current sessions. Never deletes."""
    user.is_active = False
    user.save(update_fields=["is_active"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.deactivated_at = timezone.now()
    profile.deactivated_by = actor
    profile.save(update_fields=["deactivated_at", "deactivated_by"])

    StaffInvite.objects.filter(user=user, accepted_at__isnull=True, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )

    audit.record(audit.STAFF_DEACTIVATED, actor=actor, request=request, target=user, reason=reason or "")
    revoke_sessions(user, actor=actor, request=request, reason="account deactivated")
    return user


@transaction.atomic
def reactivate_staff(user, *, actor, request=None):
    user.is_active = True
    user.save(update_fields=["is_active"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.deactivated_at = None
    profile.deactivated_by = None
    profile.save(update_fields=["deactivated_at", "deactivated_by"])

    audit.record(audit.STAFF_REACTIVATED, actor=actor, request=request, target=user)
    return user


@transaction.atomic
def set_roles(user, roles, *, actor, request=None):
    """Replaces this person's roles, recording each change individually so the
    audit log says what was added and what was taken away."""
    roles = {role for role in roles if role in ASSIGNABLE_ROLES}
    current = {group.name for group in user.groups.all() if group.name in ASSIGNABLE_ROLES}

    for role in roles - current:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        audit.record(audit.ROLE_ASSIGNED, actor=actor, request=request, target=user, role=role)

    for role in current - roles:
        group = Group.objects.filter(name=role).first()
        if group:
            user.groups.remove(group)
            audit.record(audit.ROLE_REMOVED, actor=actor, request=request, target=user, role=role)

    return user


def would_remove_last_administrator(user, new_roles):
    """True if this change would leave nobody able to administer the system.

    Locking every administrator out is unrecoverable without shell access, so
    it's refused rather than warned about.
    """
    if ADMIN_GROUP not in {g.name for g in user.groups.all()}:
        return False
    if ADMIN_GROUP in set(new_roles):
        return False
    others = (
        User.objects.filter(groups__name=ADMIN_GROUP, is_active=True)
        .exclude(pk=user.pk)
        .exists()
    )
    return not others
