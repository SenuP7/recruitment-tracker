"""Exposes the current user's unread StaffNotification count for the nav
bell, same shape as dashboard.context_processors.dashboard_access."""

from .models import StaffNotification


def staff_notifications(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"unread_staff_notification_count": 0}

    return {
        "unread_staff_notification_count": StaffNotification.objects.filter(
            recipient=user, is_read=False
        ).count()
    }
