import logging

from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.db.models import Q
from django.shortcuts import redirect
from django.views import View
from django.views.generic import DetailView, TemplateView

from django.contrib.auth.models import User

from accounts import throttling
from accounts.decorators import user_in_groups
from candidates.models import Candidate
from positions.models import Position


logger = logging.getLogger(__name__)

ROLE_SUMMARIES = {
    "Recruiter": "Creates and manages candidates, applications, positions and interview schedules across every department.",
    "HR Interviewer": "Runs HR rounds, updates interview outcomes, and writes structured feedback.",
    "Technical Interviewer": "Runs technical rounds and writes feedback, with the dashboard scoped to their own department.",
    "Senior Reviewer": "Reviews candidates across every round, updates application stages, and can moderate any feedback.",
    "Leadership Manager": "Oversees the full pipeline, updates application stages, and can edit any feedback.",
    "Candidate": "Follows their own applications in the candidate portal.",
}



class PostLoginRedirectView(LoginRequiredMixin, View):
    """Where signing in lands you. Candidates have no business on a staff
    page, and staff have none in the portal, so the two never share a
    landing page."""

    def get(self, request, *args, **kwargs):
        if getattr(request.user, "candidate", None) is not None and not user_in_groups(request.user):
            return redirect("portal:overview")
        if user_in_groups(request.user):
            return redirect("dashboard:dashboard")
        return redirect("profile")


class ProfileView(LoginRequiredMixin, DetailView):
    model = User
    template_name = "accounts/profile.html"
    context_object_name = "profile_user"

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        from django.utils import timezone

        from interviews.models import Interview, InterviewFeedback, StaffNotification

        context = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.now()
        groups = list(user.groups.order_by("name"))

        context.update({
            "roles": [{"name": g.name, "summary": ROLE_SUMMARIES.get(g.name, "")} for g in groups],
            "my_upcoming_interviews": list(
                Interview.objects.filter(interviewer=user, status="Scheduled", scheduled_date__gte=now)
                .select_related("application__candidate", "application__position")
                .order_by("scheduled_date")[:5]
            ),
            "my_interview_count": Interview.objects.filter(interviewer=user).count(),
            "my_feedback": list(
                InterviewFeedback.objects.filter(author=user, parent__isnull=True)
                .select_related("interview__application__candidate")
                .order_by("-created_at")[:5]
            ),
            "my_feedback_count": InterviewFeedback.objects.filter(author=user, parent__isnull=True).count(),
            "unread_notifications": list(
                StaffNotification.objects.filter(recipient=user, is_read=False).order_by("-created_at")[:5]
            ),
        })
        return context


def _multi_term_search(queryset, query, *field_names):
    """Splits query into words and requires every word to match at least
    one of field_names (AND across words, OR across fields per word) --
    same algorithm as dashboard.filters.apply_filters' candidate search, so
    "Jane Doe" matches first_name="Jane" + last_name="Doe" even though
    neither field alone contains the full string."""
    for term in query.split():
        term_query = Q()
        for field_name in field_names:
            term_query |= Q(**{f"{field_name}__icontains": term})
        queryset = queryset.filter(term_query)
    return queryset


class GlobalSearchView(LoginRequiredMixin, TemplateView):
    """Just needs to be logged in -- each result category is independently
    gated by its own view permission below, so a user with neither
    view_candidate nor view_position simply gets empty results in both,
    same as if those nav links weren't there for them."""

    template_name = "accounts/search_results.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()
        user = self.request.user

        candidates = []
        if query and user.has_perm("candidates.view_candidate"):
            candidates = _multi_term_search(
                Candidate.objects.all(), query, "first_name", "last_name", "email"
            ).order_by("first_name", "last_name")[:25]

        positions = []
        if query and user.has_perm("positions.view_position"):
            positions = _multi_term_search(
                Position.objects.all(), query, "title"
            ).order_by("title")[:25]

        context["query"] = query
        context["candidates"] = candidates
        context["positions"] = positions
        return context

class ThrottledLoginView(auth_views.LoginView):
    """Sign-in with brute-force protection.

    The lockout is counted per username and per IP, and a locked-out attempt
    is refused without checking the password at all, so it says nothing about
    whether the account exists. A successful sign-in clears the counters.
    """

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")
        if throttling.is_locked_out(request, username):
            form = self.get_form()
            form.is_valid()
            form.add_error(None, throttling.LOCKED_OUT_MESSAGE)
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        throttling.clear_login_attempts(request=self.request, username=form.get_user().get_username())
        return super().form_valid(form)

    def form_invalid(self, form):
        if throttling.LOCKED_OUT_MESSAGE not in form.non_field_errors():
            throttling.record_failed_login(self.request, self.request.POST.get("username", ""))
        return super().form_invalid(form)


class ThrottledPasswordResetView(auth_views.PasswordResetView):
    """Reset emails cost money and land in someone else's inbox, so the form
    can't be used as a free mailer. Throttled requests render the same 'check
    your email' page as real ones, which keeps the form quiet about who has
    an account."""

    def form_valid(self, form):
        if throttling.reset_requests_exhausted(self.request):
            logger.info("Password reset throttled for %s", throttling.client_ip(self.request))
            return HttpResponseRedirect(self.get_success_url())
        throttling.record_reset_request(self.request)
        return super().form_valid(form)
