"""Builds one complete worked example of the whole pipeline.

    python manage.py seed_demo

One candidate, one role, a real CV that gets scored, an interview that has
already happened with feedback on it, another one coming up, and logins for
every role so you can see the same data through each pair of eyes.

Everything it creates is tagged (usernames start with `demo.`, emails end in
@demo.candidflow.example), so running it again replaces the previous demo and
nothing else. `--clear` removes it and stops.
"""

import io
import os
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department, UserProfile
from candidates.models import Application, Candidate, CandidateInvite, PendingApplication
from cv_screening.matching import score_cv_against_role
from cv_screening.models import CandidateCV, CVMatchResult, RoleKeywordProfile, Skill
from interviews.models import Interview, InterviewFeedback
from positions.models import Position

DEMO_EMAIL_DOMAIN = "demo.candidflow.example"
DEMO_USER_PREFIX = "demo."
# No password lives in this file. Each run generates one and prints it, so a
# copy of the repo never hands anyone a working login. Set
# CANDIDFLOW_DEMO_PASSWORD to choose your own (handy when re-seeding often).
DEMO_PASSWORD_ENV = "CANDIDFLOW_DEMO_PASSWORD"
DEMO_TAG = "[demo]"

STAFF = [
    ("demo.recruiter", "Rita", "Nunes", "Recruiter"),
    ("demo.hr", "Hana", "Silva", "HR Interviewer"),
    ("demo.tech", "Tomas", "Ilic", "Technical Interviewer"),
    ("demo.senior", "Sara", "Boateng", "Senior Reviewer"),
    ("demo.lead", "Leo", "Marchetti", "Leadership Manager"),
    ("demo.chief", "Chiara", "Rossi", "Department Chief"),
    ("demo.admin", "Adaeze", "Nwosu", "Administrator"),
]

# Mirrors accounts/management/commands/assign_role_permissions.py, with one
# deliberate difference: the Candidate group gets nothing. Candidates use the
# portal, which scopes by their own record and needs no model permissions.
PERMISSION_MATRIX = {
    "Recruiter": {
        "candidate": ["add", "change", "delete", "view"],
        "candidatecv": ["add", "change", "delete", "view"],
        "application": ["add", "change", "delete", "view"],
        "position": ["add", "change", "delete", "view"],
        "interview": ["add", "change", "delete", "view"],
        "interviewfeedback": ["view"],
    },
    "HR Interviewer": {
        "candidate": ["view"],
        "application": ["view"],
        "position": ["view"],
        "interview": ["view", "change"],
        "interviewfeedback": ["add", "change", "view"],
    },
    "Technical Interviewer": {
        "candidate": ["view"],
        "application": ["view"],
        "position": ["view"],
        "interview": ["view", "change"],
        "interviewfeedback": ["add", "change", "view"],
    },
    "Senior Reviewer": {
        "candidate": ["view", "change"],
        "application": ["view", "change"],
        "position": ["view"],
        "interview": ["view"],
        "interviewfeedback": ["view"],
    },
    "Leadership Manager": {
        "candidate": ["view", "change"],
        "application": ["view", "change"],
        "position": ["view"],
        "interview": ["view"],
        "interviewfeedback": ["view"],
    },
    "Candidate": {},
}

CV_TEXT = """Maya Reyes
Backend Engineer

Summary
Backend engineer with six years building and running APIs in Python. Comfortable
owning a service end to end, from schema design through to what happens at 3am.

Experience
Senior Backend Engineer, Northwind Systems (2022 - present)
- Built and maintained REST APIs in Python and Django serving 40k daily users.
- Moved reporting queries onto PostgreSQL read replicas, cutting p95 latency by half.
- Packaged services with Docker and deployed them to AWS.

Backend Engineer, Latimer Analytics (2019 - 2022)
- Wrote the ingestion pipeline that processed several million events a day.
- Introduced automated testing to a codebase that had none.

Skills
Python, Django, PostgreSQL, Docker, AWS, REST APIs, automated testing
"""

APPLICANT_MESSAGE = (
    "I've spent the last six years on Python and Django services, most recently "
    "owning the reporting API at Northwind. Keen to work somewhere the backend "
    "team owns its own deployments."
)


class Command(BaseCommand):
    help = "Create one worked example of the full pipeline, with logins for every role."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Remove demo data and stop.")
        parser.add_argument(
            "--with-permissions",
            action="store_true",
            help="Also set the role groups' permissions. Changes access for real users too.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required when the database isn't local SQLite.",
        )
        parser.add_argument(
            "--base-url",
            default="http://127.0.0.1:8000",
            help="Used only to print working links at the end.",
        )

    def handle(self, *args, **options):
        self.password = os.environ.get(DEMO_PASSWORD_ENV) or secrets.token_urlsafe(12)
        self.check_database(options["yes"], clearing=options["clear"])
        self.base_url = options["base_url"].rstrip("/")

        if options["clear"]:
            removed = self.clear()
            self.stdout.write(self.style.SUCCESS(f"Removed {removed} demo records."))
            return

        with transaction.atomic():
            self.clear()
            if options["with_permissions"]:
                self.apply_permissions()
            staff = self.create_staff()
            position, profile = self.create_role()
            candidate, application = self.create_candidate(position, staff)
            self.create_interviews(application, staff)
            self.create_extras(position, staff)
            cohort_position, cohort = self.create_cohort(staff)
            pending = self.create_pending(position)
            invite = CandidateInvite.issue(candidate)

        self.report(staff, position, candidate, application, pending, invite, options)

    # -- guards ---------------------------------------------------------

    def check_database(self, confirmed, clearing=False):
        """Both writing and clearing need confirming on a real database, but
        they must say which one they're about to do -- a message about writing
        demo data invites exactly the wrong fix when you asked to remove it."""
        engine = settings.DATABASES["default"]["ENGINE"]
        if "sqlite" in engine or confirmed:
            return

        if clearing:
            raise CommandError(
                "This deletes the demo candidates, applications and logins from the database "
                "you're pointed at, which is not local SQLite.\n"
                "Re-run as:  manage.py seed_demo --clear --yes"
            )

        raise CommandError(
            "This writes demo candidates and logins into the database you're pointed at, "
            "which is not local SQLite.\n"
            "Re-run as:  manage.py seed_demo --yes"
        )

    # -- cleanup --------------------------------------------------------

    def clear(self):
        """Removes anything a previous run created, and nothing else."""
        counts = 0
        candidates = Candidate.objects.filter(email__endswith=DEMO_EMAIL_DOMAIN)
        for candidate in candidates:
            for cv in CandidateCV.objects.filter(candidate=candidate):
                cv.file.delete(save=False)
        counts += candidates.delete()[0]

        for pending in PendingApplication.objects.filter(email__endswith=DEMO_EMAIL_DOMAIN):
            pending.cv.delete(save=False)
            pending.delete()
            counts += 1

        counts += User.objects.filter(username__startswith=DEMO_USER_PREFIX).delete()[0]
        counts += User.objects.filter(email__endswith=DEMO_EMAIL_DOMAIN).delete()[0]
        counts += Position.objects.filter(description__startswith=DEMO_TAG).delete()[0]
        counts += RoleKeywordProfile.objects.filter(role_name__startswith=DEMO_TAG).delete()[0]
        return counts

    # -- permissions ----------------------------------------------------

    def apply_permissions(self):
        for group_name, models in PERMISSION_MATRIX.items():
            group, _ = Group.objects.get_or_create(name=group_name)
            group.permissions.clear()
            for model_name, actions in models.items():
                for action in actions:
                    permission = Permission.objects.filter(
                        codename=f"{action}_{model_name}"
                    ).first()
                    if permission:
                        group.permissions.add(permission)
            self.stdout.write(f"  {group_name}: {group.permissions.count()} permissions")

    # -- data -----------------------------------------------------------

    def create_staff(self):
        department, _ = Department.objects.get_or_create(name="Engineering")
        people = {}

        for username, first_name, last_name, group_name in STAFF:
            user = User.objects.create_user(
                username,
                email=f"{username.split('.')[1]}@{DEMO_EMAIL_DOMAIN}",
                password=self.password,
                first_name=first_name,
                last_name=last_name,
            )
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
            # A technical interviewer with no department sees an empty
            # dashboard -- that's the scoping rule, not a bug.
            UserProfile.objects.update_or_create(user=user, defaults={"department": department})
            people[group_name] = user

        department, _ = Department.objects.get_or_create(name="Engineering")
        department.chiefs.set([people["Department Chief"]])

        return people

    def create_role(self):
        skills = {
            name: Skill.objects.get_or_create(name=name)[0]
            for name in ("Python", "Django", "PostgreSQL", "Kubernetes", "Docker", "AWS", "React")
        }
        profile = RoleKeywordProfile.objects.create(role_name=f"{DEMO_TAG} Backend Engineer")
        # Kubernetes and React are deliberately absent from the demo CV, so the
        # score lands in the middle and the "missing required" list isn't empty --
        # which is the case a recruiter actually has to think about.
        profile.required_skills.set(
            [skills["Python"], skills["Django"], skills["PostgreSQL"], skills["Kubernetes"]]
        )
        profile.nice_to_have_skills.set([skills["Docker"], skills["AWS"], skills["React"]])

        department, _ = Department.objects.get_or_create(name="Engineering")
        position = Position.objects.create(
            title="Backend Engineer",
            description=(
                f"{DEMO_TAG} You'll build and run the APIs behind our products, working "
                "closely with product and design. We deploy several times a week and the "
                "team that writes a service is the team that operates it."
            ),
            minimum_experience=3,
            department=department,
            screening_profile=profile,
            is_open=True,
        )
        return position, profile

    def create_candidate(self, position, staff):
        now = timezone.now()
        candidate = Candidate.objects.create(
            first_name="Maya",
            last_name="Reyes",
            email=f"maya@{DEMO_EMAIL_DOMAIN}",
            phone="07700 900123",
            department=position.department,
            current_status="Technical Interview",
            source="public",
            terms_accepted_at=now - timedelta(days=12),
        )

        portal_user = User.objects.create_user(
            candidate.email,
            email=candidate.email,
            password=self.password,
            first_name=candidate.first_name,
            last_name=candidate.last_name,
        )
        portal_user.groups.add(Group.objects.get_or_create(name="Candidate")[0])
        candidate.user = portal_user
        candidate.save(update_fields=["user"])

        application = Application.objects.create(
            candidate=candidate,
            position=position,
            status="Technical Interview",
            applicant_message=APPLICANT_MESSAGE,
        )
        Application.objects.filter(pk=application.pk).update(applied_at=now - timedelta(days=12))

        self.attach_cv(candidate, position)
        return candidate, application

    def attach_cv(self, candidate, position, cv_text=None, filename=None):
        """A real .docx, so the screening score comes out of the same code
        path a genuine upload goes through."""
        import docx

        cv_text = cv_text or CV_TEXT
        filename = filename or "maya-reyes-cv.docx"

        document = docx.Document()
        for line in cv_text.strip().splitlines():
            document.add_paragraph(line)
        buffer = io.BytesIO()
        document.save(buffer)
        content = ContentFile(buffer.getvalue(), name=filename)

        cv = CandidateCV(candidate=candidate)
        try:
            cv.file.save(content.name, content, save=True)
        except Exception as error:
            # No S3 configured locally: keep the demo working by writing the
            # file next to the project instead. Opening it in the app will
            # only work once real storage is set up.
            self.stdout.write(
                self.style.WARNING(f"  Storing the CV through the configured storage failed ({error}).")
            )
            self.stdout.write("  Falling back to local media/ for the demo CV.")
            local = FileSystemStorage(location=settings.BASE_DIR / "media")
            name = local.save(f"cvs/{filename}", content)
            cv.file.name = name
            cv.save()

        cv.extracted_text = cv_text
        cv.save(update_fields=["extracted_text"])
        score_cv_against_role(cv, position.screening_profile)
        return cv

    def create_interviews(self, application, staff):
        now = timezone.now()

        hr_round = Interview.objects.create(
            application=application,
            interview_type="HR",
            scheduled_date=now - timedelta(days=4),
            status="Completed",
            assigned_interviewer=staff["HR Interviewer"],
            created_by=staff["Recruiter"],
            location="Meeting room 1",
        )
        root = InterviewFeedback.objects.create(
            interview=hr_round,
            author=staff["HR Interviewer"],
            rating=4,
            recommendation="Pass",
            comments=(
                "Explained the reporting API rewrite clearly, including what she'd do "
                "differently. Asked good questions about how we handle on-call. Motivation "
                "for the move is consistent with what's on her CV."
            ),
        )
        InterviewFeedback.objects.create(
            interview=hr_round,
            parent=root,
            author=staff["Senior Reviewer"],
            comments="Agreed. Worth pushing on system design in the technical round.",
        )

        technical = Interview.objects.create(
            application=application,
            interview_type="Technical",
            scheduled_date=now + timedelta(days=9, hours=2),
            status="Scheduled",
            assigned_interviewer=staff["Technical Interviewer"],
            created_by=staff["Recruiter"],
            location="Meeting room 2, or remote",
            meeting_link="https://meet.example.com/demo-technical",
        )

        # An offer waiting for an answer: the round is still the technical
        # interviewer's responsibility until the chief accepts.
        from interviews import delegation

        delegation.offer(
            technical,
            to_user=staff["Department Chief"],
            reason="I'm at a conference that week -- could you take this one?",
            actor=staff["Technical Interviewer"],
        )

    def create_cohort(self, staff):
        """A second role with six applicants spread across the pipeline.

        Every CV is scored through the real code path, and each one is
        written to match the profile differently -- a pipeline where
        everyone scores 100% shows a viewer nothing about what screening is
        for. The data lives in _demo_cohort.py; only the wiring is here.
        """
        from . import _demo_cohort as data

        skills = {
            name: Skill.objects.get_or_create(name=name)[0]
            for name in data.ROLE_REQUIRED + data.ROLE_NICE_TO_HAVE
        }
        profile = RoleKeywordProfile.objects.create(
            role_name=f"{DEMO_TAG} {data.ROLE_TITLE}"
        )
        profile.required_skills.set([skills[n] for n in data.ROLE_REQUIRED])
        profile.nice_to_have_skills.set([skills[n] for n in data.ROLE_NICE_TO_HAVE])

        department, _ = Department.objects.get_or_create(name="Engineering")
        position = Position.objects.create(
            title=data.ROLE_TITLE,
            description=f"{DEMO_TAG} {data.ROLE_DESCRIPTION}",
            minimum_experience=3,
            department=department,
            screening_profile=profile,
            is_open=True,
        )

        now = timezone.now()
        created = []

        for spec in data.COHORT:
            applied = now - timedelta(days=spec["applied_days_ago"])
            candidate = Candidate.objects.create(
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                email=f"{spec['handle']}@{DEMO_EMAIL_DOMAIN}",
                phone=spec["phone"],
                department=department,
                current_status=spec["status"],
                source="public",
                terms_accepted_at=applied,
            )
            application = Application.objects.create(
                candidate=candidate,
                position=position,
                status=spec["status"],
                applicant_message=spec["message"],
            )
            # applied_at is auto_now_add, so it has to be set after the fact.
            Application.objects.filter(pk=application.pk).update(applied_at=applied)

            self.attach_cv(
                candidate,
                position,
                cv_text=spec["cv"],
                filename=f"{spec['handle']}-cv.docx",
            )

            for round_spec in spec["interviews"]:
                self.create_cohort_interview(application, staff, round_spec, now)

            created.append(candidate)

        return position, created

    def create_cohort_interview(self, application, staff, spec, now):
        """One interview round for a cohort applicant, with feedback when the
        round has already happened."""
        if "days_ago" in spec:
            when = now - timedelta(days=spec["days_ago"])
        else:
            when = now + timedelta(days=spec["days_in"], hours=3)

        interview = Interview.objects.create(
            application=application,
            interview_type=spec["type"],
            scheduled_date=when,
            status=spec["status"],
            assigned_interviewer=staff[spec["role"]],
            created_by=staff["Recruiter"],
            location="Meeting room 3, or remote",
        )

        if not spec.get("comments"):
            return interview

        root = InterviewFeedback.objects.create(
            interview=interview,
            author=staff[spec["role"]],
            rating=spec["rating"],
            recommendation=spec["recommendation"] or "",
            comments=spec["comments"],
        )
        if spec.get("reply"):
            InterviewFeedback.objects.create(
                interview=interview,
                parent=root,
                author=staff[spec["reply_role"]],
                comments=spec["reply"],
            )
        return interview

    def create_extras(self, position, staff):
        """A few other applications so the pipeline chart and list filters
        have something to show. No CVs, no interviews -- they're scenery."""
        department = position.department
        others = [
            ("Ade", "Balogun", "Applied"),
            ("Iris", "Kowalski", "CV Screening"),
            ("Jonas", "Weber", "CV Screening Passed"),
            ("Priya", "Raman", "Rejected"),
        ]
        for first_name, last_name, status in others:
            candidate = Candidate.objects.create(
                first_name=first_name,
                last_name=last_name,
                email=f"{first_name.lower()}@{DEMO_EMAIL_DOMAIN}",
                phone="07700 900000",
                department=department,
                current_status=status,
            )
            Application.objects.create(candidate=candidate, position=position, status=status)

    def create_pending(self, position):
        """An application that hasn't been confirmed yet, so you can see what
        the confirmation link does."""
        import docx

        document = docx.Document()
        document.add_paragraph("Sam Okafor — Python, Django, Docker")
        buffer = io.BytesIO()
        document.save(buffer)

        try:
            return PendingApplication.start(
                position=position,
                first_name="Sam",
                last_name="Okafor",
                email=f"sam@{DEMO_EMAIL_DOMAIN}",
                phone="",
                message="Applying after seeing the role on your careers page.",
                cv=ContentFile(buffer.getvalue(), name="sam-okafor-cv.docx"),
                ip_address="127.0.0.1",
            )
        except Exception as error:
            self.stdout.write(self.style.WARNING(f"  Skipped the pending application ({error})."))
            return None

    # -- output ---------------------------------------------------------

    def report(self, staff, position, candidate, application, pending, invite, options):
        result = CVMatchResult.objects.filter(cv__candidate=candidate).first()
        write = self.stdout.write

        write("")
        write(self.style.SUCCESS("Demo data ready."))
        write("")
        write("THE WORKED EXAMPLE")
        write(f"  Role          {position.title} (open, screening profile attached)")
        write(f"  Candidate     {candidate.full_name} <{candidate.email}>")
        write(f"  Application   {application.get_status_display()}, applied 12 days ago")
        if result:
            write(f"  CV score      {round(result.score * 100)}% - {result.match_category()}, 1 required skill missing")
        write("  Interviews    HR round completed (rated 4/5, passed, with a reply)")
        write("                Technical round in 9 days, offered to the department chief")
        write("                and waiting for them to accept")
        write("")
        write("LOGINS (password for all of them: " + self.password + ")")
        write("  This password was generated for this run. It is not stored anywhere else.")
        write(f"  Staff sign-in     {self.base_url}{reverse('login')}")
        for username, first_name, last_name, group_name in STAFF:
            write(f"    {username:<16} {group_name}")
        write(f"  Candidate sign-in {self.base_url}{reverse('portal:login')}")
        write(f"    {candidate.email}")
        write("")
        write("LINKS TO TRY")
        write(f"  Careers page      {self.base_url}{reverse('careers')}")
        write(f"  Dashboard         {self.base_url}{reverse('dashboard:dashboard')}")
        write(f"  The application   {self.base_url}{reverse('application-detail', args=[application.pk])}")
        write(f"  Candidate record  {self.base_url}{reverse('candidate-detail', args=[candidate.pk])}")
        if pending:
            write(
                "  Confirm a public application (creates Sam Okafor's record):\n"
                f"    {self.base_url}{reverse('application-confirm', args=[pending.token])}"
            )
        write(
            "  Set up a candidate account from an invite:\n"
            f"    {self.base_url}{reverse('portal:accept-invite', args=[invite.token])}"
        )
        write("")
        write("TRY THIS")
        write("  1. Sign in as demo.recruiter and open the application: CV score, the")
        write("     applicant's message, and buttons to confirm the screening outcome.")
        write("  2. Sign in as demo.tech - the same pipeline, scoped to Engineering.")
        write("  3. Sign in as the candidate: the same application with no scores, no")
        write("     feedback and no interviewer names.")
        write("")

        if not options["with_permissions"]:
            empty = [
                name for name in PERMISSION_MATRIX
                if name != "Candidate" and not Group.objects.filter(name=name).exclude(permissions=None).exists()
            ]
            if empty:
                write(self.style.WARNING(
                    "Some role groups have no permissions, so those logins will hit 403s.\n"
                    "Run with --with-permissions to set them (this affects real users too)."
                ))
        write("Remove it all again with: manage.py seed_demo --clear")
        write(f"Set {DEMO_PASSWORD_ENV} before seeding if you want to choose the password.")
