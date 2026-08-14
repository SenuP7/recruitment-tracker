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

    def __str__(self):
        return f"{self.application} - {self.interview_type}"
    
class InterviewFeedback(models.Model):

    RECOMMENDATION_CHOICES = [
        ("Pass", "Pass"),
        ("Hold", "Hold"),
        ("Reject", "Reject"),
    ]

    interview = models.OneToOneField(
        Interview,
        on_delete=models.CASCADE,
        related_name="feedback"
    )

    rating = models.PositiveSmallIntegerField(
        default=3
    )

    comments = models.TextField()

    recommendation = models.CharField(
        max_length=20,
        choices=RECOMMENDATION_CHOICES
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"Feedback - {self.interview}"
    