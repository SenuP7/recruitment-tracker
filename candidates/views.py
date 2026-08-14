from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .models import Candidate, CandidateCV, Application


# ============================================================
# CANDIDATE VIEWS
# ============================================================

class CandidateListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListView
):
    model = Candidate
    template_name = "candidates/candidate_list.html"
    context_object_name = "candidates"
    permission_required = "candidates.view_candidate"
    raise_exception = True


class CandidateDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DetailView
):
    model = Candidate
    template_name = "candidates/candidate_detail.html"
    context_object_name = "candidate"
    permission_required = "candidates.view_candidate"
    raise_exception = True


class CandidateCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    CreateView
):
    model = Candidate
    template_name = "candidates/candidate_form.html"

    fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "department",
        "current_status",
    ]

    permission_required = "candidates.add_candidate"
    success_url = reverse_lazy("candidate-list")
    raise_exception = True


class CandidateUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    UpdateView
):
    model = Candidate
    template_name = "candidates/candidate_form.html"

    fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "department",
        "current_status",
    ]

    permission_required = "candidates.change_candidate"
    success_url = reverse_lazy("candidate-list")
    raise_exception = True


class CandidateDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DeleteView
):
    model = Candidate
    template_name = "candidates/candidate_confirm_delete.html"
    context_object_name = "candidate"

    permission_required = "candidates.delete_candidate"
    success_url = reverse_lazy("candidate-list")
    raise_exception = True


# ============================================================
# CANDIDATE CV VIEWS
# ============================================================

class CandidateCVListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListView
):
    model = CandidateCV
    template_name = "candidates/cv_list.html"
    context_object_name = "candidate_cvs"

    permission_required = "candidates.view_candidatecv"
    raise_exception = True


class CandidateCVCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    CreateView
):
    model = CandidateCV
    template_name = "candidates/cv_form.html"

    fields = [
        "candidate",
        "cv_file",
        "is_active",
    ]

    permission_required = "candidates.add_candidatecv"
    success_url = reverse_lazy("cv-list")
    raise_exception = True


# ============================================================
# APPLICATION VIEWS
# ============================================================

class ApplicationListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListView
):
    model = Application
    template_name = "candidates/application_list.html"
    context_object_name = "applications"

    permission_required = "candidates.view_application"
    raise_exception = True


class ApplicationDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DetailView
):
    model = Application
    template_name = "candidates/application_detail.html"
    context_object_name = "application"

    permission_required = "candidates.view_application"
    raise_exception = True


class ApplicationCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    CreateView
):
    model = Application
    template_name = "candidates/application_form.html"

    fields = [
        "candidate",
        "position",
        "status",
    ]

    permission_required = "candidates.add_application"
    success_url = reverse_lazy("application-list")
    raise_exception = True


class ApplicationUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    UpdateView
):
    model = Application
    template_name = "candidates/application_form.html"

    fields = [
        "candidate",
        "position",
        "status",
    ]

    permission_required = "candidates.change_application"
    success_url = reverse_lazy("application-list")
    raise_exception = True


class ApplicationDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DeleteView
):
    model = Application
    template_name = "candidates/application_confirm_delete.html"
    context_object_name = "application"

    permission_required = "candidates.delete_application"
    success_url = reverse_lazy("application-list")
    raise_exception = True