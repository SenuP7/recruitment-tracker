from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .models import Interview, InterviewFeedback


# ============================================================
# INTERVIEW VIEWS
# ============================================================

class InterviewListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListView
):
    model = Interview
    template_name = "interviews/interview_list.html"
    context_object_name = "interviews"

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


class InterviewCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    CreateView
):
    model = Interview
    template_name = "interviews/interview_form.html"

    fields = [
        "application",
        "interview_type",
        "scheduled_date",
        "status",
    ]

    permission_required = "interviews.add_interview"
    success_url = reverse_lazy("interview-list")
    raise_exception = True


class InterviewUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    UpdateView
):
    model = Interview
    template_name = "interviews/interview_form.html"

    fields = [
        "application",
        "interview_type",
        "scheduled_date",
        "status",
    ]

    permission_required = "interviews.change_interview"
    success_url = reverse_lazy("interview-list")
    raise_exception = True


class InterviewDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DeleteView
):
    model = Interview
    template_name = "interviews/interview_confirm_delete.html"
    context_object_name = "interview"

    permission_required = "interviews.delete_interview"
    success_url = reverse_lazy("interview-list")
    raise_exception = True


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
    CreateView
):
    model = InterviewFeedback
    template_name = "interviews/feedback_form.html"

    fields = [
        "interview",
        "rating",
        "comments",
        "recommendation",
    ]

    permission_required = "interviews.add_interviewfeedback"
    success_url = reverse_lazy("interview-list")
    raise_exception = True


class InterviewFeedbackUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    UpdateView
):
    model = InterviewFeedback
    template_name = "interviews/feedback_form.html"

    fields = [
        "interview",
        "rating",
        "comments",
        "recommendation",
    ]

    permission_required = "interviews.change_interviewfeedback"
    success_url = reverse_lazy("interview-list")
    raise_exception = True
    
class InterviewFeedbackDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DeleteView
):
    model = InterviewFeedback
    template_name = "interviews/feedback_confirm_delete.html"
    context_object_name = "feedback"

    permission_required = "interviews.delete_interviewfeedback"
    success_url = reverse_lazy("interview-list")
    raise_exception = True