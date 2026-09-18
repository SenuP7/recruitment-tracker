from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.http import HttpResponse
from django.templatetags.static import static
from django.views.generic import RedirectView


def health_check(request):
    """Hit over plain HTTP by the load balancer, so it's exempt from the
    HTTPS redirect (see SECURE_REDIRECT_EXEMPT)."""
    return HttpResponse("OK")


class FaviconRedirectView(RedirectView):
    """Resolved per request, not at import time: under hashed static storage
    the file name isn't known until collectstatic has run, and URLs are
    imported before that during a deploy."""

    permanent = True

    def get_redirect_url(self, *args, **kwargs):
        return static("img/favicon.ico")


urlpatterns = [
    # Movable via DJANGO_ADMIN_PATH: the default path is scanned constantly.
    path(f"{settings.ADMIN_PATH}/", admin.site.urls),

    path("healthz/", health_check, name="health-check"),
    path("favicon.ico", FaviconRedirectView.as_view(), name="favicon"),

    path("accounts/", include("accounts.urls")),
    path("candidates/", include("candidates.urls")),
    path("cv-screening/", include("cv_screening.urls")),
    path("positions/", include("positions.urls")),
    path("interviews/", include("interviews.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("portal/", include("portal.urls")),

    # Public site: landing, help, status, legal pages, robots/sitemap/security.txt.
    path("", include("marketing.urls")),
]