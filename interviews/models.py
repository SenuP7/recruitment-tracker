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

    # Who scheduled it. Distinct from who conducts it: a recruiter books the
    # round, an interviewer runs it, and after a delegation a third person may
    # actually turn up. Collapsing these into one field loses the answer to
    # "who arranged this?" the moment anything is reassigned.
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interviews_created"
    )

    # Who owns the round. Nullable, because scheduling doesn't require picking
    # someone up front. Who may be assigned is restricted to recruitment staff
    # in InterviewForm, not at the model level.
    assigned_interviewer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interviews_to_conduct"
    )

    location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where to go, or the room. Shown to the candidate."
    )

    meeting_link = models.URLField(
        blank=True,
        help_text="Video call link. Shown to the candidate."
    )

    def __str__(self):
        return f"{self.application} - {self.interview_type}"

    @property
    def active_delegation(self):
        """The delegation currently standing, if any. Pending counts: it is
        still the original interviewer's responsibility until accepted, but
        the offer is live and shouldn't be duplicated."""
        return self.delegations.filter(status__in=("pending", "accepted")).order_by("-created_at").first()

    @property
    def conducting_interviewer(self):
        """Who is actually expected to turn up.

        The delegate only once they have accepted -- an unanswered offer
        leaves responsibility exactly where it was.
        """
        delegation = self.delegations.filter(status="accepted").order_by("-created_at").first()
        return delegation.to_user if delegation else self.assigned_interviewer
    
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
    """In-app notification for staff users. Candidates are told about their
    applications by email instead (notification_client).
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


class InterviewDelegation(models.Model):
    """One offer to have somebody else conduct an interview.

    Kept as its own record rather than a second field on Interview, because
    the history matters: who asked, who was asked, why, whether they agreed,
    and what happened to earlier attempts. A field would be overwritten by
    the next reassignment and the trail would be gone.

    Responsibility only moves on acceptance. Until then the assigned
    interviewer still owns the round -- an offer nobody has read is not cover.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (ACCEPTED, "Accepted"),
        (DECLINED, "Declined"),
        (WITHDRAWN, "Withdrawn"),
        (EXPIRED, "Expired"),
    ]

    OPEN_STATUSES = (PENDING, ACCEPTED)

    interview = models.ForeignKey(
        Interview,
        on_delete=models.CASCADE,
        related_name="delegations"
    )

    from_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="delegations_made"
    )

    to_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="delegations_received"
    )

    reason = models.TextField(
        help_text="Why you're asking them. Internal only -- the candidate never sees it."
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)

    # Filled in when the delegate answers, so "declined, because ..." survives.
    response_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.interview} delegated to {self.to_user}"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def crosses_departments(self):
        """True when the delegate isn't in the same department as the person
        asking. Allowed -- real cover crosses teams -- but worth showing."""
        def department_of(user):
            profile = getattr(user, "profile", None)
            return getattr(profile, "department_id", None)

        if self.from_user is None:
            return False
        return department_of(self.from_user) != department_of(self.to_user)
