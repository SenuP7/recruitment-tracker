from django.contrib.auth import views as auth_views
from django.urls import path

from accounts.login_forms import CandidateLoginForm
from accounts.views import ThrottledLoginView

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.PortalOverviewView.as_view(), name="overview"),
    path(
        "login/",
        ThrottledLoginView.as_view(
            template_name="portal/login.html",
            authentication_form=CandidateLoginForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("applications/<int:pk>/", views.PortalApplicationDetailView.as_view(), name="application-detail"),
    path("applications/<int:pk>/cv/", views.PortalCVUploadView.as_view(), name="cv-upload"),
    path("cv/<int:pk>/", views.PortalCVDownloadView.as_view(), name="cv-download"),
    path("applications/<int:pk>/withdraw/", views.PortalWithdrawView.as_view(), name="withdraw"),
    path("invite/<str:token>/", views.AcceptInviteView.as_view(), name="accept-invite"),
]
