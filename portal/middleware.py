"""Keeps candidate accounts inside the portal.

Defence in depth, not the primary control: the Candidate group holds no model
permissions, so the staff views would refuse these users anyway. This turns
that 403 into a redirect back to the portal, and means a permission granted
by mistake in the database doesn't quietly open the staff app to a candidate.
"""

from django.contrib import messages
from django.shortcuts import redirect

from accounts.decorators import user_in_groups

STAFF_ONLY_PREFIXES = (
    "/candidates/",
    "/positions/",
    "/interviews/",
    "/cv-screening/",
    "/dashboard/",
    "/admin/",
    "/accounts/profile/",
    "/accounts/search/",
)


class CandidatePortalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user_in_groups(user)
            and getattr(user, "candidate", None) is not None
            and request.path.startswith(STAFF_ONLY_PREFIXES)
        ):
            messages.info(request, "That page is for the recruitment team. Here's your application instead.")
            return redirect("portal:overview")

        return self.get_response(request)
