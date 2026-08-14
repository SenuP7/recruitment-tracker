from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView

from django.contrib.auth.models import User


class ProfileView(LoginRequiredMixin, DetailView):
    model = User
    template_name = "accounts/profile.html"
    context_object_name = "profile_user"

    def get_object(self, queryset=None):
        return self.request.user