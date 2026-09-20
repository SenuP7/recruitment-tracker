from django.urls import path
from . import views

app_name = "cv_screening"

urlpatterns = [
    # List all screening results
    path(
        "results/",
        views.screening_results,
        name="screening-results",
    ),

    # View one screening result
    path(
        "results/<int:result_id>/",
        views.screening_result_detail,
        name="screening-result-detail",
    ),

    # View/download the uploaded CV
    path(
        "cv/<int:cv_id>/",
        views.view_cv,
        name="view_cv",
    ),

    path(
    "results/delete/<int:result_id>/",
    views.delete_cv_result,
    name="delete-cv-result"
    ),

    # A recruiter confirms the screening outcome; the score never sets it.
    path(
    "application/<int:application_id>/outcome/",
    views.confirm_screening_outcome,
    name="confirm-screening-outcome"
    ),

    path(
    "application/<int:application_id>/",
    views.upload_application_cv,
    name="application-upload-cv"
    ),
]