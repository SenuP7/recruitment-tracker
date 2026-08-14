from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group

ROLES = [
    "Candidate",
    "Recruiter",
    "HR Interviewer",
    "Technical Interviewer",
    "Senior Reviewer",
    "Leadership Manager",
]

class Command(BaseCommand):
    help = "Creates the six default Groups"

    def handle(self, *args, **kwargs):
        for role in ROLES:
            group, created = Group.objects.get_or_create(name=role)

            if created:
                self.stdout.write(self.style.SUCCESS(f"{role} created"))
            else:
                self.stdout.write(self.style.WARNING(f"{role} already exists"))