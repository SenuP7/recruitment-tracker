from django.contrib import admin
from django.urls import path
from django.http import HttpResponse

def health_check(request):
    return HttpResponse("OK")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", health_check),
]