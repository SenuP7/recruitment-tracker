from django.urls import path

from .views import (
    CandidateListView,
    CandidateDetailView,
    CandidateCreateView,
    CandidateUpdateView,
    CandidateDeleteView,
    CandidateInviteView,
    CandidateInviteRevokeView,
    ApplicationListView,
    ApplicationDetailView,
    ApplicationCreateView,
    ApplicationUpdateView,
    ApplicationDeleteView,
)


urlpatterns = [

    # Candidates
    path(
        "",
        CandidateListView.as_view(),
        name="candidate-list"
    ),

    path(
        "<int:pk>/",
        CandidateDetailView.as_view(),
        name="candidate-detail"
    ),

    path(
        "add/",
        CandidateCreateView.as_view(),
        name="candidate-create"
    ),

    path(
        "<int:pk>/edit/",
        CandidateUpdateView.as_view(),
        name="candidate-update"
    ),

    path(
        "<int:pk>/delete/",
        CandidateDeleteView.as_view(),
        name="candidate-delete"
    ),

    path(
        "<int:pk>/invite/",
        CandidateInviteView.as_view(),
        name="candidate-invite"
    ),

    path(
        "<int:pk>/invite/revoke/",
        CandidateInviteRevokeView.as_view(),
        name="candidate-invite-revoke"
    ),

    # Applications
    path(
        "applications/",
        ApplicationListView.as_view(),
        name="application-list"
    ),

    path(
        "applications/<int:pk>/",
        ApplicationDetailView.as_view(),
        name="application-detail"
    ),

    path(
        "applications/add/",
        ApplicationCreateView.as_view(),
        name="application-create"
    ),

    path(
        "applications/<int:pk>/edit/",
        ApplicationUpdateView.as_view(),
        name="application-update"
    ),

    path(
        "applications/<int:pk>/delete/",
        ApplicationDeleteView.as_view(),
        name="application-delete"
    ),
]