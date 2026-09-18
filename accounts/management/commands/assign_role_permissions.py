from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

# CandidateCV lives in cv_screening; it was moved out of candidates in
# migration 0002 and this import was never updated, so the command has
# been failing on import since then.
from candidates.models import Candidate, Application
from cv_screening.models import CandidateCV
from interviews.models import Interview, InterviewFeedback
from positions.models import Position


class Command(BaseCommand):
    help = "Assign permissions to all recruitment system roles"

    def handle(self, *args, **kwargs):

        # ---------------------------------------------------------
        # GET THE SIX ROLE GROUPS
        # ---------------------------------------------------------

        # get_or_create so a fresh environment can be set up in one command;
        # the six original groups already exist in the real database.
        recruiter, _ = Group.objects.get_or_create(name="Recruiter")
        hr, _ = Group.objects.get_or_create(name="HR Interviewer")
        tech, _ = Group.objects.get_or_create(name="Technical Interviewer")
        senior, _ = Group.objects.get_or_create(name="Senior Reviewer")
        leadership, _ = Group.objects.get_or_create(name="Leadership Manager")
        candidate, _ = Group.objects.get_or_create(name="Candidate")

        # Roles added with the staff/delegation work.
        chief, _ = Group.objects.get_or_create(name="Department Chief")
        administrator, _ = Group.objects.get_or_create(name="Administrator")

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
        # DEPARTMENT CHIEF
        # ---------------------------------------------------------
        #
        # A chief runs a department and may be asked to conduct interviews
        # their team can't take, so they read the recruitment record and
        # write feedback -- but they don't administer candidates.

        add_permissions(chief, Candidate, ["view"])
        add_permissions(chief, Application, ["view"])
        add_permissions(chief, Position, ["view"])
        add_permissions(chief, Interview, ["view", "change"])
        add_permissions(chief, InterviewFeedback, ["add", "change", "view"])

        # ---------------------------------------------------------
        # ADMINISTRATOR
        # ---------------------------------------------------------
        #
        # Runs the system: full access to recruitment records, plus the staff
        # and audit screens, which are gated on the group itself rather than
        # on a model permission (see accounts/staff_views.py).

        for model in (Candidate, CandidateCV, Application, Position, Interview):
            add_permissions(administrator, model, ["add", "change", "delete", "view"])
        add_permissions(administrator, InterviewFeedback, ["view", "change", "delete"])

        # ---------------------------------------------------------
        # CANDIDATE
        # ---------------------------------------------------------
        #
        # Deliberately none. These four view_* permissions used to be granted
        # here, and they are model-wide: they let a candidate account read
        # EVERY candidate, application, interview and feedback entry, not just
        # their own. Candidates now use the portal (portal/), which scopes
        # every query to the record linked to their login and needs no model
        # permissions at all. Granting any here would reopen that hole.

        candidate.permissions.clear()

        self.stdout.write(
            f"{candidate.name}: cleared (the portal scopes by record, not by permission)"
        )

        # ---------------------------------------------------------
        # FINISHED
        # ---------------------------------------------------------

        self.stdout.write(
            self.style.SUCCESS(
                "RBAC permissions configured successfully."
            )
        )