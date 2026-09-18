"""Candidate portal.

Deliberately separate from the staff app: these views never take a candidate
id from the URL, and the Candidate group holds no model permissions, so a
candidate account can only ever reach its own records. What candidates are
not shown -- interview feedback, CV match scores, interviewer names, and any
sign of other applicants -- is simply never put in the context.
"""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import Group, User
from django.http import FileResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, TemplateView

from accounts import audit
from candidates.models import Application, CandidateInvite
from candidates.views import build_journey
from cv_screening.models import CandidateCV
from cv_screening.uploads import score_cv_safely, validate_cv_file
from interviews.models import Interview, StaffNotification

from .forms import AcceptInviteForm, CandidateCVUploadForm, email_is_available
from .mixins import CandidateRequiredMixin

CANDIDATE_GROUP = "Candidate"

# Interview fields a candidate may see. Who is interviewing them is
# deliberately not among them.
INTERVIEW_FIELDS = (
    "id", "application_id", "interview_type", "scheduled_date", "status",
    "location", "meeting_link",
)


def candidate_interviews(applications):
    """Rounds a candidate may see.

    `only()` is an efficiency measure, not the control: the control is that
    no template renders an interviewer, and nothing here exposes one. The
    candidate sees the round, when it is, where it is, and which team is
    running it -- never who, and never that it was delegated.
    """
    return (
        Interview.objects.filter(application__in=applications)
        .select_related("application__position__department")
        .only(*INTERVIEW_FIELDS, "application__position__department__name",
              "application__position__title")
        .order_by("scheduled_date")
    )


class PortalOverviewView(CandidateRequiredMixin, TemplateView):
    template_name = "portal/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        applications = list(self.get_applications().order_by("-applied_at"))
        now = timezone.now()

        interviews = list(candidate_interviews(applications))
        by_application = {}
        for interview in interviews:
            by_application.setdefault(interview.application_id, []).append(interview)

        cards = []
        for application in applications:
            rounds = by_application.get(application.id, [])
            cards.append({
                "application": application,
                "next_interview": next(
                    (i for i in rounds if i.status == "Scheduled" and i.scheduled_date >= now), None
                ),
                "needs_cv": application.candidate_can_upload_cv and not self._has_cv(application),
            })

        context.update({
            "cards": cards,
            "open_count": sum(1 for a in applications if not a.is_closed),
            "upcoming_interviews": [
                i for i in interviews if i.status == "Scheduled" and i.scheduled_date >= now
            ][:5],
            "todo": [card for card in cards if card["needs_cv"]],
        })
        return context

    def _has_cv(self, application):
        return CandidateCV.objects.filter(candidate_id=application.candidate_id).exists()


class PortalApplicationDetailView(CandidateRequiredMixin, DetailView):
    template_name = "portal/application_detail.html"
    context_object_name = "application"

    def get_queryset(self):
        return self.get_applications()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = self.object
        now = timezone.now()
        rounds = list(candidate_interviews([application]))

        context.update({
            "journey": build_journey(application.status),
            "interviews": rounds,
            "next_interview": next(
                (i for i in rounds if i.status == "Scheduled" and i.scheduled_date >= now), None
            ),
            "cv": CandidateCV.objects.filter(candidate=self.candidate).order_by("-uploaded_at").first(),
            "can_upload_cv": application.candidate_can_upload_cv,
            "can_withdraw": application.candidate_can_withdraw,
        })
        return context


class PortalCVUploadView(CandidateRequiredMixin, View):
    """A candidate's own upload scores the CV but never decides the outcome --
    a recruiter confirms pass or fail (see cv_screening.views)."""

    template_name = "portal/cv_upload.html"

    def get_application(self):
        return get_object_or_404(self.get_applications(), pk=self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        application = self.get_application()
        return render(request, self.template_name, self._context(application, CandidateCVUploadForm()))

    def post(self, request, *args, **kwargs):
        application = self.get_application()
        if not application.candidate_can_upload_cv:
            messages.error(request, "This application's CV can no longer be changed.")
            return redirect("portal:application-detail", pk=application.pk)

        uploaded_file = request.FILES.get("cv_file")
        error = validate_cv_file(uploaded_file)
        if error:
            return render(
                request,
                self.template_name,
                self._context(application, CandidateCVUploadForm(), error=error),
            )

        cv = CandidateCV.objects.create(candidate=self.candidate, file=uploaded_file)

        # A CV we can't parse is still a CV a recruiter can open, so it is
        # kept and the candidate is told -- not turned into a 500.
        _, unreadable = score_cv_safely(cv, application.position.screening_profile)

        if application.status == "Applied":
            application.status = "CV Screening"
            application.save(update_fields=["status"])

        messages.success(request, "Your CV was uploaded. The recruitment team will review it.")
        if unreadable:
            messages.warning(request, unreadable)
        return redirect("portal:application-detail", pk=application.pk)

    def _context(self, application, form, error=None):
        return {
            "application": application,
            "candidate": self.candidate,
            "form": form,
            "error": error,
            "existing_cv": CandidateCV.objects.filter(candidate=self.candidate)
            .order_by("-uploaded_at")
            .first(),
        }


class PortalWithdrawView(CandidateRequiredMixin, View):
    template_name = "portal/withdraw_confirm.html"

    def get_application(self):
        return get_object_or_404(self.get_applications(), pk=self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        application = self.get_application()
        return render(request, self.template_name, {"application": application, "candidate": self.candidate})

    def post(self, request, *args, **kwargs):
        application = self.get_application()
        if not application.candidate_can_withdraw:
            messages.error(request, "This application is already closed.")
            return redirect("portal:application-detail", pk=application.pk)

        with transaction.atomic():
            application.status = "Withdrawn"
            application.save(update_fields=["status"])
            cancelled = Interview.objects.filter(application=application, status="Scheduled")
            recipients = self._staff_to_notify(cancelled)
            cancelled.update(status="Cancelled")
            self._notify(recipients, application)

        audit.record(
            audit.APPLICATION_WITHDRAWN,
            actor=request.user,
            request=request,
            target=application,
            position=application.position.title,
        )
        messages.success(request, "Your application has been withdrawn.")
        return redirect("portal:overview")

    def _staff_to_notify(self, scheduled_interviews):
        """The people who would otherwise turn up to an interview, plus the
        recruiters who own the pipeline."""
        interviewers = set(
            scheduled_interviews.exclude(assigned_interviewer__isnull=True).values_list(
                "assigned_interviewer_id", flat=True
            )
        )
        recruiters = set(
            User.objects.filter(groups__name="Recruiter", is_active=True).values_list("id", flat=True)
        )
        return User.objects.filter(id__in=interviewers | recruiters)

    def _notify(self, recipients, application):
        link = reverse("application-detail", kwargs={"pk": application.pk})
        message = f"{self.candidate.full_name} withdrew their application for {application.position.title}."
        StaffNotification.objects.bulk_create([
            StaffNotification(recipient=recipient, message=message, link=link)
            for recipient in recipients
        ])


class AcceptInviteView(View):
    """Public: turns a valid invite token into a candidate login.

    An expired, revoked, already-used or unknown token all render the same
    page, so the token can't be probed to learn whether a candidate exists.
    """

    template_name = "portal/accept_invite.html"
    invalid_template = "portal/invite_invalid.html"

    def get_invite(self):
        return (
            CandidateInvite.objects.filter(token=self.kwargs["token"])
            .select_related("candidate", "candidate__user")
            .first()
        )

    def get(self, request, *args, **kwargs):
        invite = self.get_invite()
        if invite is None or not invite.is_usable:
            return render(request, self.invalid_template, status=404)
        if not email_is_available(invite.email):
            return render(request, self.invalid_template, {"email_taken": True}, status=409)
        return render(request, self.template_name, self._context(invite, AcceptInviteForm(user=User())))

    def post(self, request, *args, **kwargs):
        invite = self.get_invite()
        if invite is None or not invite.is_usable:
            return render(request, self.invalid_template, status=404)
        if not email_is_available(invite.email):
            return render(request, self.invalid_template, {"email_taken": True}, status=409)

        user = User(username=invite.email, email=invite.email)
        user.first_name = invite.candidate.first_name
        user.last_name = invite.candidate.last_name
        form = AcceptInviteForm(user=user, data=request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._context(invite, form))

        with transaction.atomic():
            form.save()
            group, _ = Group.objects.get_or_create(name=CANDIDATE_GROUP)
            user.groups.add(group)
            candidate = invite.candidate
            candidate.user = user
            candidate.save(update_fields=["user"])
            invite.accepted_at = timezone.now()
            invite.save(update_fields=["accepted_at"])

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Your account is ready.")
        return redirect("portal:overview")

    def _context(self, invite, form):
        return {"invite": invite, "candidate": invite.candidate, "form": form}


PORTAL_HOME = reverse_lazy("portal:overview")


class PortalCVDownloadView(CandidateRequiredMixin, View):
    """Lets a candidate open the CV they sent us.

    Scoped to their own record: the staff download view
    (cv_screening.view_cv) takes any CV id and is staff-only, so without this
    a candidate had no way to check what we actually hold about them.
    """

    def get(self, request, *args, **kwargs):
        cv = get_object_or_404(CandidateCV, pk=self.kwargs["pk"], candidate=self.candidate)
        return FileResponse(
            cv.file.open("rb"),
            as_attachment=True,
            filename=cv.file.name.rsplit("/", 1)[-1],
        )
