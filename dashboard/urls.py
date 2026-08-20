from django.urls import path

from .views import DashboardResultsView, DashboardView

app_name = "dashboard"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("results/", DashboardResultsView.as_view(), name="dashboard-results"),
]
