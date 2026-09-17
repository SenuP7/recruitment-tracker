from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import DetailView, TemplateView

from django.contrib.auth.models import User

from candidates.models import Candidate
from positions.models import Position


ROLE_SUMMARIES = {
    "Recruiter": "Creates and manages candidates, applications, positions and interview schedules across every department.",
    "HR Interviewer": "Runs HR rounds, updates interview outcomes, and writes structured feedback.",
    "Technical Interviewer": "Runs technical rounds and writes feedback, with the dashboard scoped to their own department.",
    "Senior Reviewer": "Reviews candidates across every round, updates application stages, and can moderate any feedback.",
    "Leadership Manager": "Oversees the full pipeline, updates application stages, and can edit any feedback.",
    "Candidate": "Can browse open positions.",
}


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