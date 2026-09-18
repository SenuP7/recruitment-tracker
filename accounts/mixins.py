from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class GroupRequiredMixin(LoginRequiredMixin):
    allowed_groups = []

    def dispatch(self, request, *args, **kwargs):
        # Not signed in is a different answer from not allowed. Let
        # LoginRequiredMixin send them to the sign-in page: since staff
        # sessions expire after 8 hours, and a deactivated account is
        # signed out mid-visit, a bare 403 would be the normal daily
        # experience of a session running out.
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        user_groups = request.user.groups.values_list(
            "name",
            flat=True
        )

        if not any(group in self.allowed_groups for group in user_groups):
            raise PermissionDenied(
                "You do not have permission to access this page."
            )

        return super().dispatch(request, *args, **kwargs)


class DepartmentRequiredMixin(GroupRequiredMixin):
    def get_user_department(self):
        try:
            return self.request.user.profile.department
        except AttributeError:
            return None

    def check_department(self, obj):
        user_department = self.get_user_department()

        if user_department is None:
            raise PermissionDenied(
                "Your account is not assigned to a department."
            )

        obj_department = getattr(obj, "department", None)

        if obj_department != user_department:
            raise PermissionDenied(
                "You do not have access to this department."
            )

        return True


class AuthorOrGroupRequiredMixin(LoginRequiredMixin):
    """Object-level check: allows the object's author, a superuser, or a
    member of override_groups; denies (403) otherwise. Mirrors
    DepartmentRequiredMixin's shape -- an object-level narrowing layered on
    top of whatever coarser gate the view already uses."""

    author_field = "author"
    override_groups = ()

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user

        is_author = getattr(self.object, f"{self.author_field}_id", None) == user.id
        is_override = (
            user.is_superuser
            or user.groups.filter(name__in=self.override_groups).exists()
        )

        if not (is_author or is_override):
            raise PermissionDenied("You can only edit your own feedback.")

        return super().dispatch(request, *args, **kwargs)