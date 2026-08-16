from django.urls import path
from . import views

app_name = "cv_screening"

urlpatterns = [
    # Upload and screen a CV against a role
    path(
        "upload/<int:role_profile_id>/",
        views.upload_cv,
        name="upload-cv",
    ),

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
]