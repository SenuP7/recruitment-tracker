"""Forces a first-password change before anything else.

An account created by an administrator starts with `must_change_password`
set. Until the person has set their own password, every page sends them to
the setup link -- a check in individual views would be one forgotten view
away from being pointless.
"""

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

# Pages someone must still be able to reach while they are being forced to
# set a password.
ALLOWED_PREFIXES = ("/accounts/staff/setup/", "/accounts/logout/", "/accounts/password-reset/", "/static/", "/healthz")


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(getattr(user, "profile", None), "must_change_password", False)
            and not request.path.startswith(ALLOWED_PREFIXES)
        ):
            messages.info(request, "Please set your own password before continuing.")
            return redirect(reverse("password_reset"))

        return self.get_response(request)
