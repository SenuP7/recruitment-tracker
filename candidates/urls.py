from django.urls import path

from .views import (
    CandidateListView,
    CandidateDetailView,
    CandidateCreateView,
    CandidateUpdateView,
    CandidateDeleteView,
    CandidateCVListView,
    CandidateCVCreateView,
    ApplicationListView,
    ApplicationDetailView,
    ApplicationCreateView,
    ApplicationUpdateView,
    ApplicationDeleteView,
)


urlpatterns = [
    path("", CandidateListView.as_view(), name="candidate-list"),
    path("<int:pk>/", CandidateDetailView.as_view(), name="candidate-detail"),
    path("create/", CandidateCreateView.as_view(), name="candidate-create"),
    path("<int:pk>/edit/", CandidateUpdateView.as_view(), name="candidate-update"),
    path("<int:pk>/delete/", CandidateDeleteView.as_view(), name="candidate-delete"),

    path("cv/", CandidateCVListView.as_view(), name="cv-list"),
    path("cv/create/", CandidateCVCreateView.as_view(), name="cv-create"),

    path("applications/", ApplicationListView.as_view(), name="application-list"),
    path(
        "applications/<int:pk>/",
        ApplicationDetailView.as_view(),
        name="application-detail",
    ),
    path(
        "applications/create/",
        ApplicationCreateView.as_view(),
        name="application-create",
    ),
    path(
        "applications/<int:pk>/edit/",
        ApplicationUpdateView.as_view(),
        name="application-update",
    ),
    path(
        "applications/<int:pk>/delete/",
        ApplicationDeleteView.as_view(),
        name="application-delete",
    ),
]