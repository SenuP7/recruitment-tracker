from django.contrib import admin
from django.urls import include, path
from django.http import HttpResponse


def health_check(request):
    return HttpResponse("OK")


urlpatterns = [
    path("admin/", admin.site.urls),

    path("", health_check, name="health-check"),

    path("accounts/", include("accounts.urls")),
    path("candidates/", include("candidates.urls")),
    path("positions/", include("positions.urls")),
    path("interviews/", include("interviews.urls")),
]