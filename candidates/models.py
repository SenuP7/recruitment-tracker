import secrets
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from accounts.models import Department
from positions.models import Position

# How long a portal invite stays usable. Long enough for someone who checks
# email weekly, short enough that a forwarded link goes stale.
INVITE_VALID_DAYS = 7

# A public application waits this long for its email to be confirmed before
# it's discarded. Shorter than an invite: nothing is in the pipeline yet.
PENDING_VALID_DAYS = 3


class Candidate(models.Model):

    first_name = models.CharField(max_length=100)

    last_name = models.CharField(max_length=100)

    email = models.EmailField(unique=True)

    phone = models.CharField(max_length=20)

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    current_status = models.CharField(
        max_length=50,
        default="Applied"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    # Where the record came from. Recruiters need to tell a colleague's entry
    # apart from something typed into the public form by anyone at all.
    SOURCE_CHOICES = [
        ("staff", "Added by staff"),
        ("public", "Applied online"),
    ]

    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="staff")

    # When they agreed to the terms, set only for public applications.
    terms_accepted_at = models.DateTimeField(null=True, blank=True)

    # The candidate's own portal login, set when they accept an invite.
    # Nullable because most candidate records are entered by recruiters and
    # never get a login; SET_NULL so deleting an account doesn't take the
    # recruitment record with it. This is the ONLY link between a login and
    # a candidate -- portal views scope by it, never by matching emails.
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="candidate"
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def has_portal_access(self):
        return self.user_id is not None and self.user.is_active


class CandidateInvite(models.Model):
    """One emailed invitation for a candidate to create their portal login.

    Stored rather than signed-and-forgotten so staff can see who was invited
    and when, and so an invite can be revoked before it's used."""

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="invites"
    )

    # Snapshot of where the invite was sent, which stays true even if the
    # candidate's email is corrected later.
    email = models.EmailField()

    token = models.CharField(max_length=64, unique=True, db_index=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite for {self.email}"

    @classmethod
    def issue(cls, candidate, created_by=None):
        """Revokes any invite still outstanding, then creates a fresh one --
        only the newest link should ever work."""
        now = timezone.now()
        cls.objects.filter(
            candidate=candidate, accepted_at__isnull=True, revoked_at__isnull=True
        ).update(revoked_at=now)
        return cls.objects.create(
            candidate=candidate,
            email=candidate.email,
            token=secrets.token_urlsafe(32),
            created_by=created_by,
            expires_at=now + timedelta(days=INVITE_VALID_DAYS),
        )

    @property
    def is_usable(self):
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
            and self.candidate.user_id is None
        )


class PendingApplication(models.Model):
    """A public application waiting for its email address to be confirmed.

    Nothing here is in the recruitment pipeline. Recruiters never see these
    rows, and no Candidate or Application exists until someone clicks the
    link we email them -- so anyone can type any address into the public
    form without putting a fake application under another person's name, or
    attaching anything to an existing candidate record.
    """

    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        related_name="pending_applications"
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    message = models.TextField(blank=True)

    cv = models.FileField(upload_to="pending_cvs/")

    token = models.CharField(max_length=64, unique=True, db_index=True)

    # Kept only to rate limit the form, and cleared once the application is
    # confirmed -- it isn't part of the recruitment record.
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    terms_accepted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pending application from {self.email}"

    @classmethod
    def start(cls, *, position, first_name, last_name, email, phone, message, cv, ip_address):
        now = timezone.now()
        return cls.objects.create(
            position=position,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            message=message,
            cv=cv,
            ip_address=ip_address,
            token=secrets.token_urlsafe(32),
            terms_accepted_at=now,
            expires_at=now + timedelta(days=PENDING_VALID_DAYS),
        )

    @property
    def is_usable(self):
        return self.verified_at is None and self.expires_at > timezone.now()

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Application(models.Model):

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="applications"
    )

    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        related_name="applications"
    )

    STATUS_CHOICES = [
    ("Applied", "Applied"),
    ("CV Screening", "CV Screening"),
    ("CV Screening Passed", "CV Screening Passed"),
    ("CV Screening Failed", "CV Screening Failed"),
    ("HR Interview", "HR Interview"),
    ("Technical Interview", "Technical Interview"),
    ("Senior Review", "Senior Review"),
    ("Accepted", "Accepted"),
    ("Rejected", "Rejected"),
    ("Withdrawn", "Withdrawn"),
]

    # Screening outcomes are confirmed by a recruiter, never set automatically
    # by a CV score -- see cv_screening.views. Uploading a CV only moves an
    # application to "CV Screening".
    SCREENING_DECIDED_STATUSES = ("CV Screening Passed", "CV Screening Failed")
    CLOSED_STATUSES = ("Accepted", "Rejected", "Withdrawn")
    

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="Applied"
    )

    applied_at = models.DateTimeField(
        auto_now_add=True
    )

    # What the applicant wrote on the public form, kept with the application
    # so recruiters see it and it survives the pending record being purged.
    applicant_message = models.TextField(blank=True)

    def __str__(self):
        return f"{self.candidate} - {self.position}"

    @property
    def is_closed(self):
        return self.status in self.CLOSED_STATUSES

    @property
    def candidate_can_upload_cv(self):
        """Candidates may add or replace a CV until a recruiter decides the
        screening outcome; after that the file interviewers read is fixed."""
        return self.status in ("Applied", "CV Screening")

    @property
    def candidate_can_withdraw(self):
        return not self.is_closed