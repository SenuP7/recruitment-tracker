from django.db import models
from accounts.models import Department


class Position(models.Model):
    title = models.CharField(max_length=150)
    description = models.TextField()
    minimum_experience = models.PositiveIntegerField(default=0)
    is_open = models.BooleanField(default=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE
    )

    is_open = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title