from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from candidates.models import Candidate, CandidateCV, Application
from interviews.models import Interview, InterviewFeedback
from positions.models import Position


class Command(BaseCommand):
    help = "Assign permissions to all recruitment system roles"

    def handle(self, *args, **kwargs):

        # ---------------------------------------------------------
        # GET THE SIX ROLE GROUPS
        # ---------------------------------------------------------

        recruiter = Group.objects.get(name="Recruiter")
        hr = Group.objects.get(name="HR Interviewer")
        tech = Group.objects.get(name="Technical Interviewer")
        senior = Group.objects.get(name="Senior Reviewer")
        leadership = Group.objects.get(name="Leadership Manager")
        candidate = Group.objects.get(name="Candidate")

        self.stdout.write(
            self.style.SUCCESS("Groups loaded successfully.")
        )

        # ---------------------------------------------------------
        # HELPER FUNCTION
        # ---------------------------------------------------------

        def get_permission(model, action):
            content_type = ContentType.objects.get_for_model(model)

            codename = f"{action}_{model._meta.model_name}"

            return Permission.objects.get(
                content_type=content_type,
                codename=codename
            )

        def add_permissions(group, model, actions):
            for action in actions:
                permission = get_permission(model, action)
                group.permissions.add(permission)

                self.stdout.write(
                    f"{group.name}: added {permission.codename}"
                )

        # ---------------------------------------------------------
        # RECRUITER
        # ---------------------------------------------------------

        add_permissions(
            recruiter,
            Candidate,
            ["add", "change", "delete", "view"]
        )

        add_permissions(
            recruiter,
            CandidateCV,
            ["add", "change", "delete", "view"]
        )

        add_permissions(
            recruiter,
            Application,
            ["add", "change", "delete", "view"]
        )

        add_permissions(
            recruiter,
            Position,
            ["add", "change", "delete", "view"]
        )

        add_permissions(
            recruiter,
            Interview,
            ["add", "change", "delete", "view"]
        )

        add_permissions(
            recruiter,
            InterviewFeedback,
            ["view"]
        )

        # ---------------------------------------------------------
        # HR INTERVIEWER
        # ---------------------------------------------------------

        add_permissions(
            hr,
            Candidate,
            ["view"]
        )

        add_permissions(
            hr,
            Application,
            ["view"]
        )

        add_permissions(
            hr,
            Position,
            ["view"]
        )

        add_permissions(
            hr,
            Interview,
            ["view", "change"]
        )

        add_permissions(
            hr,
            InterviewFeedback,
            ["add", "change", "view"]
        )

        # ---------------------------------------------------------
        # TECHNICAL INTERVIEWER
        # ---------------------------------------------------------

        add_permissions(
            tech,
            Candidate,
            ["view"]
        )

        add_permissions(
            tech,
            Application,
            ["view"]
        )

        add_permissions(
            tech,
            Position,
            ["view"]
        )

        add_permissions(
            tech,
            Interview,
            ["view", "change"]
        )

        add_permissions(
            tech,
            InterviewFeedback,
            ["add", "change", "view"]
        )

        # ---------------------------------------------------------
        # SENIOR REVIEWER
        # ---------------------------------------------------------

        add_permissions(
            senior,
            Candidate,
            ["view", "change"]
        )

        add_permissions(
            senior,
            Application,
            ["view", "change"]
        )

        add_permissions(
            senior,
            Position,
            ["view"]
        )

        add_permissions(
            senior,
            Interview,
            ["view"]
        )

        add_permissions(
            senior,
            InterviewFeedback,
            ["view"]
        )

        # ---------------------------------------------------------
        # LEADERSHIP MANAGER
        # ---------------------------------------------------------

        add_permissions(
            leadership,
            Candidate,
            ["view", "change"]
        )

        add_permissions(
            leadership,
            Application,
            ["view", "change"]
        )

        add_permissions(
            leadership,
            Position,
            ["view"]
        )

        add_permissions(
            leadership,
            Interview,
            ["view"]
        )

        add_permissions(
            leadership,
            InterviewFeedback,
            ["view"]
        )

        # ---------------------------------------------------------
        # CANDIDATE
        # ---------------------------------------------------------

        add_permissions(
            candidate,
            Candidate,
            ["view"]
        )

        add_permissions(
            candidate,
            Application,
            ["view"]
        )

        add_permissions(
            candidate,
            Interview,
            ["view"]
        )

        add_permissions(
            candidate,
            InterviewFeedback,
            ["view"]
        )

        # ---------------------------------------------------------
        # FINISHED
        # ---------------------------------------------------------

        self.stdout.write(
            self.style.SUCCESS(
                "RBAC permissions configured successfully."
            )
        )