from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from candidates.models import Application


class Interview(models.Model):

    INTERVIEW_TYPES = [
        ("HR", "HR"),
        ("Technical", "Technical"),
        ("Senior Review", "Senior Review"),
    ]

    STATUS_CHOICES = [
        ("Scheduled", "Scheduled"),
        ("Completed", "Completed"),
        ("Cancelled", "Cancelled"),
    ]

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="interviews"
    )

    interview_type = models.CharField(
        max_length=30,
        choices=INTERVIEW_TYPES
    )

    scheduled_date = models.DateTimeField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Scheduled"
    )

    # Nullable -- existing interviews have no assigned interviewer, and
    # scheduling an interview doesn't require picking one up front. Who can
    # be assigned is restricted to RECRUITMENT_STAFF_GROUPS at the form
    # level (InterviewForm), not enforced here at the model level.
    interviewer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interviews_to_conduct"
    )

    def __str__(self):
        return f"{self.application} - {self.interview_type}"
    
class InterviewFeedback(models.Model):

    RECOMMENDATION_CHOICES = [
        ("Pass", "Pass"),
        ("Hold", "Hold"),
        ("Reject", "Reject"),
    ]

    interview = models.ForeignKey(
        Interview,
        on_delete=models.CASCADE,
        related_name="feedback_entries"
    )

    # Self-referential -- null/blank means this is a root feedback entry;
    # set means this is a threaded reply to another InterviewFeedback.
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies"
    )

    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="interview_feedback"
    )

    # Nullable at the DB level -- replies don't carry a rating. Required for
    # root feedback is enforced in FeedbackForm.clean(), not here.
    rating = models.PositiveSmallIntegerField(
        default=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    comments = models.TextField()

    # blank=True -- doesn't apply to replies. Required for root feedback is
    # enforced in FeedbackForm.clean(), same as rating.
    recommendation = models.CharField(
        max_length=20,
        choices=RECOMMENDATION_CHOICES,
        blank=True,
        default=""
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"Feedback - {self.interview}"


class FeedbackAuditLog(models.Model):

    ACTION_CHOICES = [
        ("EDITED", "EDITED"),
        ("DELETED", "DELETED"),
    ]

    # SET_NULL (not CASCADE) is deliberate: a DELETED entry logs the deletion
    # of this very row, so if it cascaded away with the feedback it would
    # destroy the one record of that deletion ever happening.
    feedback = models.ForeignKey(
        InterviewFeedback,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_entries"
    )

    # Snapshot of which interview this was about -- survives even after
    # `feedback` is nulled out by a deletion, so the log entry stays
    # meaningful once the feedback it describes no longer exists.
    interview = models.ForeignKey(
        Interview,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+"
    )

    action = models.CharField(
        max_length=10,
        choices=ACTION_CHOICES,
        default="EDITED"
    )

    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+"
    )

    changed_at = models.DateTimeField(
        auto_now_add=True
    )

    # e.g. {"rating": {"old": 3, "new": 4}, "comments": {"old": "...", "new": "..."}}
    # For a DELETED entry, "new" is always null (the field's final value at delete time).
    diff = models.JSONField()

    def __str__(self):
        return f"{self.action} - {self.interview_id} @ {self.changed_at}"


class StaffNotification(models.Model):
    """In-app notification for staff users (not candidates -- see the
    dormant `notifications` app for that, deliberately left untouched).
    Currently only triggered when someone other than the feedback's author
    edits or deletes it; `link` is a relative URL to the relevant page."""

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="staff_notifications"
    )

    message = models.CharField(max_length=255)

    link = models.CharField(max_length=255, blank=True)

    is_read = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient} - {self.message[:40]}"
