from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .models import Position


# ============================================================
# POSITION LIST
# ============================================================

class PositionListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListView
):
    model = Position
    template_name = "positions/position_list.html"
    context_object_name = "positions"

    permission_required = "positions.view_position"
    raise_exception = True


# ============================================================
# POSITION DETAIL
# ============================================================

class PositionDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DetailView
):
    model = Position
    template_name = "positions/position_detail.html"
    context_object_name = "position"

    permission_required = "positions.view_position"
    raise_exception = True


# ============================================================
# CREATE POSITION
# ============================================================

class PositionCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    CreateView
):
    model = Position
    template_name = "positions/position_form.html"

    fields = [
        "title",
        "description",
        "minimum_experience",
        "is_open",
        "department",
    ]

    permission_required = "positions.add_position"
    success_url = reverse_lazy("position-list")
    raise_exception = True


# ============================================================
# UPDATE POSITION
# ============================================================

class PositionUpdateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    UpdateView
):
    model = Position
    template_name = "positions/position_form.html"

    fields = [
        "title",
        "description",
        "minimum_experience",
        "is_open",
        "department",
    ]

    permission_required = "positions.change_position"
    success_url = reverse_lazy("position-list")
    raise_exception = True


# ============================================================
# DELETE POSITION
# ============================================================

class PositionDeleteView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DeleteView
):
    model = Position
    template_name = "positions/position_confirm_delete.html"
    context_object_name = "position"

    permission_required = "positions.delete_position"
    success_url = reverse_lazy("position-list")
    raise_exception = True