from django.urls import path

from .views import DashboardExportView, DashboardResultsView, DashboardView

app_name = "dashboard"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("results/", DashboardResultsView.as_view(), name="dashboard-results"),
    path("export/", DashboardExportView.as_view(), name="dashboard-export"),
]
