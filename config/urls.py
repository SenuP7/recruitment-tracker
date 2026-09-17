from django.contrib import admin
from django.urls import include, path
from django.http import HttpResponse
from django.templatetags.static import static
from django.views.generic import RedirectView


def health_check(request):
    return HttpResponse("OK")


urlpatterns = [
    path("admin/", admin.site.urls),

    path("healthz/", health_check, name="health-check"),
    path("favicon.ico", RedirectView.as_view(url=static("img/favicon.ico"), permanent=True)),

    path("accounts/", include("accounts.urls")),
    path("candidates/", include("candidates.urls")),
    path("cv-screening/", include("cv_screening.urls")),
    path("positions/", include("positions.urls")),
    path("interviews/", include("interviews.urls")),
    path("dashboard/", include("dashboard.urls")),

    # Public site: landing, help, status, legal pages, robots/sitemap/security.txt.
    path("", include("marketing.urls")),
]