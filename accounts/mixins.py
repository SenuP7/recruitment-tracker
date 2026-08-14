from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class GroupRequiredMixin(LoginRequiredMixin):
    allowed_groups = []

    def dispatch(self, request, *args, **kwargs):
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