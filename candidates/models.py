from django.db import models
from accounts.models import Department
from positions.models import Position

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

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class CandidateCV(models.Model):

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="cvs"
    )

    cv_file = models.FileField(
        upload_to="candidate_cvs/"
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True
    )

    is_active = models.BooleanField(
        default=True
    )

    def __str__(self):
        return f"{self.candidate} CV"

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
    ("HR Interview", "HR Interview"),
    ("Technical Interview", "Technical Interview"),
    ("Senior Review", "Senior Review"),
    ("Accepted", "Accepted"),
    ("Rejected", "Rejected"),
    ]
    
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="Applied"
    )

    applied_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.candidate} - {self.position}"