from django.urls import path
from .views import upload_cv


urlpatterns = [
    path(
        "upload/<int:role_profile_id>/",
        upload_cv,
        name="upload-cv"
    ),
]