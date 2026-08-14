from django.urls import path

from .views import (
    PositionListView,
    PositionDetailView,
    PositionCreateView,
    PositionUpdateView,
    PositionDeleteView,
)


urlpatterns = [
    path("", PositionListView.as_view(), name="position-list"),
    path("<int:pk>/", PositionDetailView.as_view(), name="position-detail"),
    path("create/", PositionCreateView.as_view(), name="position-create"),
    path("<int:pk>/edit/", PositionUpdateView.as_view(), name="position-update"),
    path("<int:pk>/delete/", PositionDeleteView.as_view(), name="position-delete"),
]