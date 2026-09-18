from django.db import models
from django.contrib.auth.models import User

# How long a new staff member has to set their first password.
STAFF_INVITE_VALID_DAYS = 7

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)

    # Who chairs this department. A many-to-many on purpose: deputies and
    # shared leadership are normal, and "chief" is a fact about a department
    # rather than a property of a person -- the matching "Department Chief"
    # group carries the permissions.
    chiefs = models.ManyToManyField(
        User,
        blank=True,
        related_name="chief_of_departments",
    )

    def __str__(self):
        return self.name

    def active_chiefs(self):
        return self.chiefs.filter(is_active=True)
    
class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile"
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users"
    )

    job_title = models.CharField(max_length=120, blank=True)

    # Set on an admin-created account so the person chooses their own password
    # before doing anything else -- an administrator should never know a
    # colleague's password.
    must_change_password = models.BooleanField(default=False)

    # Leavers are deactivated, never deleted: deleting would orphan their
    # feedback and their audit trail. `User.is_active` does the actual
    # blocking; these record when and by whom.
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    def __str__(self):
        return self.user.username

    @property
    def is_deactivated(self):
        return not self.user.is_active


class StaffInvite(models.Model):
    """A link that lets a new staff member set their own first password.

    Mirrors CandidateInvite deliberately: the same expiry-and-revoke rules,
    the same "expired, used, revoked and unknown all look identical" handling,
    so there is one story for account setup rather than two.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="staff_invites")
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Staff invite for {self.email}"

    @classmethod
    def issue(cls, user, created_by=None):
        import secrets
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        cls.objects.filter(user=user, accepted_at__isnull=True, revoked_at__isnull=True).update(revoked_at=now)
        return cls.objects.create(
            user=user,
            email=user.email,
            token=secrets.token_urlsafe(32),
            created_by=created_by,
            expires_at=now + timedelta(days=STAFF_INVITE_VALID_DAYS),
        )

    @property
    def is_usable(self):
        from django.utils import timezone

        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
            and self.user.is_active
        )


class AuditEvent(models.Model):
    """Append-only record of who did what. See accounts/audit.py.

    Actor and target are kept as ids *and* as text snapshots: the ids let you
    follow a link while the record still exists, and the snapshots keep the
    entry meaningful once it doesn't.
    """

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_label = models.CharField(max_length=150)

    action = models.CharField(max_length=64, db_index=True)

    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.CharField(max_length=50, blank=True)
    target_label = models.CharField(max_length=200, blank=True)

    detail = models.JSONField(default=dict, blank=True)

    # Only kept for authentication events -- see audit.record().
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_label} {self.action}"

    def save(self, *args, **kwargs):
        """Refuses to rewrite an existing entry. An audit log that can be
        edited after the fact is not evidence of anything."""
        if self.pk is not None:
            raise ValueError("Audit events are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    @property
    def action_label(self):
        from .audit import ACTION_LABELS

        return ACTION_LABELS.get(self.action, self.action)
