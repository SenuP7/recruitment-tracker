from django.db import models
from accounts.models import Department
from cv_screening.models import RoleKeywordProfile


class Position(models.Model):

    title = models.CharField(max_length=150)

    description = models.TextField()

    minimum_experience = models.PositiveIntegerField(default=0)

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE
    )

    screening_profile = models.ForeignKey(
        RoleKeywordProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    is_open = models.BooleanField(default=True)

    created_at = models.DateTimeField(
        auto_now_add=True
    )


    def __str__(self):
        return self.title