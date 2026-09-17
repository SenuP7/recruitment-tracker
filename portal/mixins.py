"""The portal's single security boundary.

Every portal view starts from `self.candidate`, which is always the record
linked to the logged-in user -- there is no view anywhere in this app that
takes a candidate id from the URL, so one candidate cannot address another
candidate's data at all.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.urls import reverse_lazy

from accounts.decorators import user_in_groups


class CandidateRequiredMixin(LoginRequiredMixin):
    """Allows only a user with a linked Candidate record. Recruitment staff
    are refused even if someone links them by mistake: an account is either a
    staff account or a candidate account, never both."""

    login_url = reverse_lazy("portal:login")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            candidate = getattr(request.user, "candidate", None)
            if candidate is None:
                raise PermissionDenied("This area is for candidates with a Candidflow account.")
            if user_in_groups(request.user):
                raise PermissionDenied("Staff accounts can't use the candidate portal.")
            self.candidate = candidate
        return super().dispatch(request, *args, **kwargs)

    def get_applications(self):
        """The only queryset the portal builds application pages from."""
        from candidates.models import Application

        return Application.objects.filter(candidate=self.candidate).select_related(
            "position", "position__department"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["candidate"] = self.candidate
        return context
