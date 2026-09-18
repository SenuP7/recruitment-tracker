from django.db import models
from django.contrib.auth.models import User

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name
    
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

    def __str__(self):
        return self.user.username


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
