from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
# Our subclass: sends signed-out visitors to sign in instead of a bare 403.
from accounts.mixins import PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
    TemplateView,
)

from accounts.decorators import RECRUITMENT_STAFF_GROUPS, user_in_groups
from accounts.listing import ListToolbarMixin, Tab
from accounts.mixins import AuthorOrGroupRequiredMixin

from accounts import audit
from accounts.staff import is_administrator
from . import delegation
from .forms import FeedbackForm, InterviewForm
from .models import (
    FeedbackAuditLog,
    Interview,
    InterviewDelegation,
    InterviewFeedback,
    StaffNotification,
)

# Roles allowed to edit feedback they didn't author themselves -- the
# "authorized role" half of AC3, confirmed with the user. Kept as a module
# constant (same pattern as accounts.decorators.RECRUITMENT_STAFF_GROUPS)
# rather than a Django permission, since permissions here are hand-managed in
# the DB (see CLAUDE.md) and Leadership Manager/Senior Reviewer don't
# currently hold interviews.change_interviewfeedback.
FEEDBACK_EDIT_OVERRIDE_GROUPS = ("Leadership Manager", "Senior Reviewer")


def _notify_feedback_author_if_not_self(feedback, actor, verb, interview_pk):
    """Notifies the feedback's author that someone else acted on their
    feedback. No-op if there's no author to notify (SET_NULL'd) or the actor
    IS the author (editing/deleting your own feedback isn't news to you)."""
    if feedback.author_id is None or feedback.author_id == actor.id:
        return
    StaffNotification.objects.create(
        recipient=feedback.author,
        message=f"Your feedback on {feedback.interview} was {verb} by {actor.username}.",
        link=reverse("feedback-thread", kwargs={"interview_pk": interview_pk}),
    )


# ============================================================
# INTERVIEW VIEWS
# ============================================================

class InterviewListToolbarMixin(ListToolbarMixin):
    search_fields = (
        "application__candidate__first_name",
        "application__candidate__last_name",
        "application__position__title",
    )
    search_placeholder = "Search by candidate or position"
    sort_options = {
        "newest": ("Newest", ("-id",)),
        "soonest": ("Soonest first", ("scheduled_date", "id")),
        "latest": ("Latest date first", ("-scheduled_date", "-id")),
    }
    default_sort = "newest"

    def get_tabs(self):
        # Evaluated per request so "upcoming" and "overdue" move with the clock.
        now = timezone.now()
        return [
            Tab("all", "All"),
            Tab("upcoming", "Upcoming", Q(status="Scheduled", scheduled_date__gte=now)),
            Tab("overdue", "Needs update", Q(status="Scheduled", scheduled_date__lt=now)),
            Tab("completed", "Completed", Q(status="Completed")),
            Tab("cancelled", "Cancelled", Q(status="Cancelled")),
        ]

    def apply_extra_filters(self, queryset):
        interview_type = self.request.GET.get("type", "").strip()
        valid = {choice[0] for choice in Interview.INTERVIEW_TYPES}
        self.active_type = interview_type if interview_type in valid else ""
        if self.active_type:
            queryset = queryset.filter(interview_type=self.active_type)
        return queryset

    def get_extra_toolbar_context(self):
        return {
            "interview_types": [choice[0] for choice in Interview.INTERVIEW_TYPES],
            "active_type": self.active_type,
            "now": timezone.now(),
        }

    def annotate(self, queryset):
        return queryset.select_related(
            "application__candidate", "application__position", "assigned_interviewer"
        ).annotate(feedback_count=Count("feedback_entries", filter=Q(feedback_entries__parent__isnull=True)))


class InterviewListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    InterviewListToolbarMixin,
    ListView
):
    model = Interview
    template_name = "interviews/interview_list.html"
    context_object_name = "interviews"
    paginate_by = 25

    def get_base_queryset(self):
        return self.annotate(Interview.objects.all())

    permission_required = "interviews.view_interview"
    raise_exception = True


class MyInterviewsListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    InterviewListToolbarMixin,
    ListView
):
    """Same permission and template as InterviewListView, scoped to the
    interviews this person is actually expected to conduct: the ones assigned
    to them, plus any delegation they have accepted. An offer they haven't
    answered is deliberately absent -- it isn't theirs until they say so, and
    it appears as a notification instead."""

    model = Interview
    template_name = "interviews/interview_list.html"
    context_object_name = "interviews"
    paginate_by = 25

    def get_base_queryset(self):
        user = self.request.user
        return self.annotate(
            Interview.objects.filter(
                Q(assigned_interviewer=user)
                | Q(delegations__to_user=user, delegations__status=InterviewDelegation.ACCEPTED)
            ).distinct()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["my_interviews_only"] = True
        return context

    permission_required = "interviews.view_interview"
    raise_exception = True


class InterviewDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DetailView
):
    model = Interview
    template_name = "interviews/interview_detail.html"
    context_object_name = "interview"

    permission_required = "interviews.view_interview"
    raise_exception = True

    def get_queryset(self):
        return Interview.objects.select_related(
            "application__candidate",
            "application__candidate__department",
            "application__position",
            "application__position__department",
            "assigned_interviewer",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        interview = self.object
        user = self.request.user
        can_view_feedback = user.has_perm("interviews.view_interviewfeedback")

        feedback_summary = None
        latest_feedback = []
        if can_view_feedback:
            roots = interview.feedback_entries.filter(parent__isnull=True)
            aggregate = roots.aggregate(count=Count("pk"), average=Avg("rating"))
            recommendations = dict(
                roots.exclude(recommendation="").values_list("recommendation").annotate(n=Count("pk"))
            )
            feedback_summary = {
                "count": aggregate["count"],
                "average": round(aggregate["average"], 1) if aggregate["average"] is not None else None,
                "replies": interview.feedback_entries.filter(parent__isnull=False).count(),
                "recommendations": [
                    {"label": label, "count": recommendations.get(label, 0)}
                    for label, _ in InterviewFeedback.RECOMMENDATION_CHOICES
                ],
            }
            latest_feedback = list(
                roots.select_related("author").annotate(reply_count=Count("replies")).order_by("-created_at")[:3]
            )

        now = timezone.now()

        # Ownership and delegation. `conducting_interviewer` is the answer to
        # "who is actually turning up", which is the assigned interviewer
        # until somebody has accepted a delegation.
        current_delegation = (
            interview.delegations.filter(status__in=InterviewDelegation.OPEN_STATUSES)
            .select_related("from_user", "to_user")
            .first()
        )

        context.update({
            "delegation": current_delegation,
            "delegation_history": list(
                interview.delegations.select_related("from_user", "to_user")[:10]
            ),
            "conducting_interviewer": interview.conducting_interviewer,
            "can_delegate": (
                interview.status == "Scheduled" and delegation.can_delegate(user, interview)
            ),
            "can_respond_to_delegation": (
                current_delegation is not None and delegation.can_respond(user, current_delegation)
            ),
            "can_withdraw_delegation": (
                current_delegation is not None
                and current_delegation.is_open
                and (
                    current_delegation.from_user_id == user.pk
                    or is_administrator(user)
                    or interview.assigned_interviewer_id == user.pk
                )
            ),
            "can_view_feedback": can_view_feedback,
            "feedback_summary": feedback_summary,
            "latest_feedback": latest_feedback,
            "is_upcoming": interview.status == "Scheduled" and interview.scheduled_date >= now,
            "is_overdue": interview.status == "Scheduled" and interview.scheduled_date < now,
            "other_rounds": list(
                interview.application.interviews.exclude(pk=interview.pk)
                .select_related("assigned_interviewer")
                .order_by("scheduled_date")
            ),
        })
        return context


class InterviewCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    CreateView
):
    model = Interview
    template_name = "interviews/interview_form.html"
    form_class = InterviewForm

    permission_required = "interviews.add_interview"
    success_url = reverse_lazy("interview-list")
    success_message = "Interview created successfully."
    raise_exception = True

    def form_valid(self, form):
        # Who scheduled it, which is not necessarily who conducts it.
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        audit.record(
            audit.INTERVIEW_CREATED,
            request=self.request,
            target=self.object,
            interviewer=(
                self.object.assigned_interviewer.get_username()
                if self.object.assigned_interviewer
                else None
            ),
        )
        return response


class InterviewUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    UpdateView
):
    model = Interview
    template_name = "interviews/interview_form.html"
    form_class = InterviewForm

    permission_required = "interviews.change_interview"
    success_url = reverse_lazy("interview-list")
    success_message = "Interview updated successfully."
    raise_exception = True

    def form_valid(self, form):
        """Records the change, and closes any open delegation once the round
        is no longer happening -- an offer on a cancelled interview is just
        noise in somebody's list."""
        was_status = Interview.objects.values_list("status", flat=True).get(pk=self.object.pk)
        response = super().form_valid(form)

        action = {
            "Cancelled": audit.INTERVIEW_CANCELLED,
            "Completed": audit.INTERVIEW_COMPLETED,
        }.get(self.object.status if self.object.status != was_status else "", audit.INTERVIEW_UPDATED)
        audit.record(action, request=self.request, target=self.object, status=self.object.status)

        if self.object.status in ("Cancelled", "Completed"):
            delegation.close_for_interview(self.object, actor=self.request.user, request=self.request)

        return response


class InterviewDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    DeleteView
):
    model = Interview
    template_name = "interviews/interview_confirm_delete.html"
    context_object_name = "interview"

    permission_required = "interviews.delete_interview"
    success_url = reverse_lazy("interview-list")
    success_message = "Interview deleted successfully."
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cascade"] = [("feedback entry", "feedback entries", self.object.feedback_entries.count())]
        return context


# ============================================================
# INTERVIEW FEEDBACK VIEWS
# ============================================================

class InterviewFeedbackDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DetailView
):
    model = InterviewFeedback
    template_name = "interviews/feedback_detail.html"
    context_object_name = "feedback"

    permission_required = "interviews.view_interviewfeedback"
    raise_exception = True


class InterviewFeedbackCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    CreateView
):
    """Creates a root feedback entry (parent=None) for an interview."""

    model = InterviewFeedback
    form_class = FeedbackForm
    template_name = "interviews/feedback_form.html"

    permission_required = "interviews.add_interviewfeedback"
    success_message = "Feedback submitted successfully."
    raise_exception = True

    def get_initial(self):
        # Links from an interview pass ?interview=<pk> so the form opens
        # already pointed at it; the field stays editable and validated.
        initial = super().get_initial()
        interview_id = self.request.GET.get("interview", "")
        if interview_id.isdigit():
            initial["interview"] = int(interview_id)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        interview_id = context["form"]["interview"].value()
        context["context_interview"] = (
            Interview.objects.select_related("application__candidate", "application__position", "assigned_interviewer")
            .filter(pk=interview_id)
            .first()
            if str(interview_id or "").isdigit()
            else None
        )
        return context

    def form_valid(self, form):
        form.instance.author = self.request.user
        form.instance.parent = None
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("feedback-thread", kwargs={"interview_pk": self.object.interview_id})


class InterviewFeedbackReplyCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    SuccessMessageMixin,
    CreateView
):
    """Creates a threaded reply under an existing feedback entry. The
    interview is inherited from the parent, never user-chosen -- a reply
    can't be attached to a different interview than the thread it's replying
    in."""

    model = InterviewFeedback
    form_class = FeedbackForm
    template_name = "interviews/feedback_reply_form.html"

    permission_required = "interviews.add_interviewfeedback"
    success_message = "Reply posted successfully."
    raise_exception = True

    def dispatch(self, request, *args, **kwargs):
        self.parent_feedback = get_object_or_404(InterviewFeedback, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["is_reply"] = True
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["parent_feedback"] = self.parent_feedback
        return context

    def form_valid(self, form):
        form.instance.author = self.request.user
        form.instance.parent = self.parent_feedback
        form.instance.interview = self.parent_feedback.interview
        form.instance.rating = None  # field is popped from the form for replies, but
        # the model's rating default=3 would otherwise still apply -- a reply must not
        # silently inherit that default.
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("feedback-thread", kwargs={"interview_pk": self.parent_feedback.interview_id})


class InterviewFeedbackUpdateView(
    AuthorOrGroupRequiredMixin,
    SuccessMessageMixin,
    UpdateView
):
    """Edit access is NOT gated on the interviews.change_interviewfeedback
    Django permission (see FEEDBACK_EDIT_OVERRIDE_GROUPS docstring above) --
    the coarse gate is "is recruitment staff at all" (user_in_groups), and
    the real decision is AuthorOrGroupRequiredMixin: the feedback's own
    author, a superuser, or Leadership Manager/Senior Reviewer."""

    model = InterviewFeedback
    form_class = FeedbackForm
    success_message = "Feedback updated successfully."
    template_name = "interviews/feedback_form.html"

    override_groups = FEEDBACK_EDIT_OVERRIDE_GROUPS

    def dispatch(self, request, *args, **kwargs):
        if not user_in_groups(request.user, RECRUITMENT_STAFF_GROUPS):
            raise PermissionDenied("You do not have permission to access this page.")
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Snapshot before any form binding mutates the in-memory instance --
        # ModelForm validation writes cleaned data onto self.instance before
        # save() is ever called, so this must happen at fetch time.
        self._before = {"rating": obj.rating, "comments": obj.comments}
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["is_reply"] = self.object.parent_id is not None
        return kwargs

    def get_success_url(self):
        return reverse("feedback-thread", kwargs={"interview_pk": self.object.interview_id})

    def form_valid(self, form):
        before = self._before
        response = super().form_valid(form)

        after = {"rating": self.object.rating, "comments": self.object.comments}
        diff = {
            field: {"old": before[field], "new": after[field]}
            for field in before
            if before[field] != after[field]
        }
        if diff:
            FeedbackAuditLog.objects.create(
                feedback=self.object,
                interview=self.object.interview,
                action="EDITED",
                changed_by=self.request.user,
                diff=diff,
            )
            _notify_feedback_author_if_not_self(
                self.object, self.request.user, "edited", self.object.interview_id
            )
        return response


class FeedbackThreadView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    TemplateView
):
    """Renders every root feedback entry for an interview with its replies
    nested under it -- the "threaded, not flat" view AC2 asks for. The
    nesting is just the ORM relationship, prefetched to avoid N+1: one query
    for roots, one prefetch query for all their replies, regardless of how
    many threads/replies exist."""

    template_name = "interviews/feedback_thread.html"
    permission_required = "interviews.view_interviewfeedback"
    raise_exception = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        interview = get_object_or_404(Interview, pk=self.kwargs["interview_pk"])
        threads = list(
            InterviewFeedback.objects.filter(interview=interview, parent__isnull=True)
            .select_related("author")
            .prefetch_related("replies__author")
            .order_by("created_at")
        )

        user = self.request.user
        is_override = user.is_superuser or user.groups.filter(
            name__in=FEEDBACK_EDIT_OVERRIDE_GROUPS
        ).exists()
        for thread in threads:
            thread.can_edit = is_override or user == thread.author
            for reply in thread.replies.all():
                reply.can_edit = is_override or user == reply.author

        ratings = [thread.rating for thread in threads if thread.rating]
        context["interview"] = interview
        context["feedback_threads"] = threads
        context["average_rating"] = round(sum(ratings) / len(ratings), 1) if ratings else None
        context["reply_count"] = sum(len(thread.replies.all()) for thread in threads)
        context["history"] = list(
            FeedbackAuditLog.objects.filter(interview=interview)
            .select_related("changed_by")
            .order_by("-changed_at")[:6]
        )
        return context


class InterviewFeedbackDeleteView(
    PermissionRequiredMixin,
    AuthorOrGroupRequiredMixin,
    SuccessMessageMixin,
    DeleteView
):
    """Coarse gate: interviews.delete_interviewfeedback (granted to
    HR Interviewer, Technical Interviewer, Senior Reviewer, Leadership
    Manager -- not Recruiter/Candidate). Fine gate: the same author-or-
    override rule as edit (AuthorOrGroupRequiredMixin), so having the
    permission lets you delete YOUR OWN feedback, or anyone's if you're in
    FEEDBACK_EDIT_OVERRIDE_GROUPS."""

    model = InterviewFeedback
    template_name = "interviews/feedback_confirm_delete.html"
    context_object_name = "feedback"

    permission_required = "interviews.delete_interviewfeedback"
    raise_exception = True
    override_groups = FEEDBACK_EDIT_OVERRIDE_GROUPS
    success_message = "Feedback deleted successfully."

    def get_success_url(self):
        return reverse("feedback-thread", kwargs={"interview_pk": self.object.interview_id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cascade"] = [("reply", "replies", self.object.replies.count())]
        return context

    def form_valid(self, form):
        # Runs before self.object.delete() (see BaseDeleteView.form_valid) --
        # self.object still has its pre-deletion field values here.
        FeedbackAuditLog.objects.create(
            feedback=self.object,
            interview=self.object.interview,
            action="DELETED",
            changed_by=self.request.user,
            diff={
                "rating": {"old": self.object.rating, "new": None},
                "comments": {"old": self.object.comments, "new": None},
            },
        )
        _notify_feedback_author_if_not_self(
            self.object, self.request.user, "deleted", self.object.interview_id
        )
        return super().form_valid(form)


class StaffNotificationListView(LoginRequiredMixin, ListView):
    """Just needs to be logged in -- every user sees only their own
    notifications (queryset scoped to request.user), no group/permission
    gate needed on top of that."""

    model = StaffNotification
    template_name = "interviews/staff_notification_list.html"
    context_object_name = "notifications"

    def get_queryset(self):
        return StaffNotification.objects.filter(recipient=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["today"] = timezone.localdate()
        return context

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # TemplateResponse renders lazily, so render now -- otherwise the
        # update below runs first and nothing ever displays as unread.
        response.render()
        # Viewing the list marks everything in it as read -- no separate
        # "mark read" control needed for a first pass.
        self.get_queryset().filter(is_read=False).update(is_read=True)
        return response

# ============================================================
# DELEGATION
# ============================================================

class DelegateInterviewView(LoginRequiredMixin, View):
    """Offering a round to someone else.

    Authorisation is checked server-side on both GET and POST: hiding the
    button would stop nobody from posting the form.
    """

    template_name = "interviews/delegate_form.html"

    def get_interview(self):
        return get_object_or_404(
            Interview.objects.select_related("application__candidate", "application__position"),
            pk=self.kwargs["pk"],
        )

    def get(self, request, *args, **kwargs):
        interview = self.get_interview()
        if not delegation.can_delegate(request.user, interview):
            raise PermissionDenied("Only the assigned interviewer, a chief of that department or an administrator can delegate this.")
        return render(request, self.template_name, self.page(interview))

    def post(self, request, *args, **kwargs):
        interview = self.get_interview()
        if not delegation.can_delegate(request.user, interview):
            raise PermissionDenied("Only the assigned interviewer, a chief of that department or an administrator can delegate this.")

        if interview.status != "Scheduled":
            messages.error(request, "Only a scheduled interview can be delegated.")
            return redirect("interview-detail", pk=interview.pk)

        to_user_id = request.POST.get("to_user", "")
        reason = request.POST.get("reason", "").strip()
        candidates = delegation.eligible_delegates(interview, exclude_user=request.user)
        chosen = next((user for user in candidates if str(user.pk) == to_user_id), None)

        errors = {}
        if chosen is None:
            errors["to_user"] = "Choose who should conduct this interview."
        if not reason:
            errors["reason"] = "Say why you're asking them. It's recorded, and it's internal."
        if errors:
            return render(request, self.template_name, self.page(interview, errors=errors, reason=reason))

        delegation.offer(interview, to_user=chosen, reason=reason, actor=request.user, request=request)
        messages.success(
            request,
            f"Asked {chosen.get_full_name() or chosen.get_username()} to conduct this interview. "
            "It stays yours until they accept.",
        )
        return redirect("interview-detail", pk=interview.pk)

    def page(self, interview, errors=None, reason=""):
        return {
            "interview": interview,
            "delegates": delegation.eligible_delegates(interview, exclude_user=self.request.user),
            "chief_ids": set(
                getattr(interview.application.position, "department", None).chiefs.values_list("id", flat=True)
            ) if getattr(interview.application.position, "department", None) else set(),
            "errors": errors or {},
            "reason": reason,
        }


class DelegationRespondView(LoginRequiredMixin, View):
    """Accept or decline. Only the person who was asked may do either."""

    def post(self, request, pk, *args, **kwargs):
        record = get_object_or_404(
            InterviewDelegation.objects.select_related("interview__application__candidate"), pk=pk
        )

        if not delegation.can_respond(request.user, record):
            raise PermissionDenied("This delegation isn't yours to answer.")

        note = request.POST.get("note", "").strip()
        action = request.POST.get("action")

        if action == "accept":
            delegation.accept(record, actor=request.user, request=request, note=note)
            messages.success(request, "You're down to conduct this interview.")
        elif action == "decline":
            if not note:
                messages.error(request, "Please say why you can't take it, so it can be covered.")
                return redirect("interview-detail", pk=record.interview.pk)
            delegation.decline(record, actor=request.user, request=request, note=note)
            messages.success(request, "Declined. It's gone back to whoever asked you.")
        else:
            messages.error(request, "Choose whether you're accepting or declining.")

        return redirect("interview-detail", pk=record.interview.pk)


class DelegationWithdrawView(LoginRequiredMixin, View):
    """Taking back an offer, by whoever made it or an administrator."""

    def post(self, request, pk, *args, **kwargs):
        record = get_object_or_404(InterviewDelegation, pk=pk)

        allowed = (
            record.from_user_id == request.user.pk
            or is_administrator(request.user)
            or record.interview.assigned_interviewer_id == request.user.pk
        )
        if not allowed:
            raise PermissionDenied("Only the person who asked, or an administrator, can withdraw this.")
        if not record.is_open:
            messages.info(request, "That delegation is already closed.")
            return redirect("interview-detail", pk=record.interview.pk)

        delegation.withdraw(record, actor=request.user, request=request)
        messages.success(request, "Delegation withdrawn.")
        return redirect("interview-detail", pk=record.interview.pk)
