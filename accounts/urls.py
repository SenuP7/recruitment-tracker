from django.urls import path
from django.contrib.auth import views as auth_views

from .login_forms import StaffLoginForm
from .staff_views import (
    DepartmentChiefsView,
    DepartmentListView,
    RevokeMySessionsView,
    StaffAcceptInviteView,
    StaffCreateView,
    StaffDeactivateView,
    StaffListView,
    StaffReactivateView,
    StaffResendInviteView,
    StaffRolesView,
)
from .password_reset import PipelinePasswordResetForm
from .views import (
    AuditLogView,
    GlobalSearchView,
    QuickSearchView,
    PostLoginRedirectView,
    ProfileView,
    ThrottledLoginView,
    ThrottledPasswordResetView,
)


urlpatterns = [
    path(
        "login/",
        ThrottledLoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=StaffLoginForm,
        ),
        name="login",
    ),

    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),

    path(
        "after-login/",
        PostLoginRedirectView.as_view(),
        name="post-login-redirect",
    ),

    # Password reset. The email goes out through the notification pipeline
    # (see accounts/password_reset.py), not Django's own EMAIL_BACKEND.
    path(
        "password-reset/",
        ThrottledPasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            form_class=PipelinePasswordResetForm,
            success_url="/accounts/password-reset/sent/",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url="/accounts/password-reset/complete/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),

    path(
        "profile/",
        ProfileView.as_view(),
        name="profile",
    ),

    # Staff account administration.
    path("staff/", StaffListView.as_view(), name="staff-list"),
    path("staff/new/", StaffCreateView.as_view(), name="staff-create"),
    path("staff/<int:pk>/roles/", StaffRolesView.as_view(), name="staff-roles"),
    path("staff/<int:pk>/deactivate/", StaffDeactivateView.as_view(), name="staff-deactivate"),
    path("staff/<int:pk>/reactivate/", StaffReactivateView.as_view(), name="staff-reactivate"),
    path("staff/<int:pk>/resend-invite/", StaffResendInviteView.as_view(), name="staff-resend-invite"),
    path("staff/setup/<str:token>/", StaffAcceptInviteView.as_view(), name="staff-accept-invite"),
    path("departments/", DepartmentListView.as_view(), name="department-list"),
    path("departments/<int:pk>/chiefs/", DepartmentChiefsView.as_view(), name="department-chiefs"),
    path("sessions/revoke/", RevokeMySessionsView.as_view(), name="revoke-my-sessions"),

    path(
        "audit-log/",
        AuditLogView.as_view(),
        name="audit-log",
    ),

    path(
        "search/quick/",
        QuickSearchView.as_view(),
        name="quick-search",
    ),
    path(
        "search/",
        GlobalSearchView.as_view(),
        name="global-search",
    ),
]