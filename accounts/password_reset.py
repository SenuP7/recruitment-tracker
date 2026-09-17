"""Password reset that goes out through the notification pipeline.

Django would normally send this itself via EMAIL_BACKEND, which would mean a
second mail route to configure. Instead the form publishes a `password_reset`
event to the same SQS/Lambda/SES path as every other email the app sends.
"""

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.urls import reverse

from notification_client import event_types
from notification_client.publisher import publish_event


class PipelinePasswordResetForm(PasswordResetForm):
    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        """Django builds `context` (uid, token, protocol, domain, user); we
        turn it into a link and hand it to the publisher. The templates
        Django would have rendered are unused on purpose -- the wording lives
        with the other email bodies in notification-service."""
        user = context["user"]
        path = reverse(
            "password_reset_confirm",
            kwargs={"uidb64": context["uid"], "token": context["token"]},
        )
        reset_url = f"{context['protocol']}://{context['domain']}{path}"

        publish_event(
            event_types.PASSWORD_RESET,
            recipient_email=to_email,
            recipient_name=user.get_full_name() or user.get_username(),
            context={
                "recipient_name": user.first_name or user.get_username(),
                "company_name": settings.CANDIDFLOW_COMPANY_NAME,
                "reset_url": reset_url,
                "valid_hours": round(settings.PASSWORD_RESET_TIMEOUT / 3600),
            },
        )
