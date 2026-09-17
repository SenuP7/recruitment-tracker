"""Two sign-in doors, one accounts system.

Staff sign in with credentials the organisation issues them; candidates sign
in with the email address they applied with. Each form refuses the other
kind of account, so people don't land in an area that will only refuse them.

These checks run after the password has already been verified, so they say
nothing about accounts that don't exist.
"""

from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .decorators import user_in_groups


def is_candidate_account(user):
    return getattr(user, "candidate", None) is not None and not user_in_groups(user)


class StaffLoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "candidate_account": (
            "That's a candidate account. Sign in at the candidate portal to follow "
            "your application."
        ),
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if is_candidate_account(user):
            raise ValidationError(self.error_messages["candidate_account"], code="candidate_account")


class CandidateLoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "staff_account": (
            "That's a team account. Sign in at the staff sign-in page instead."
        ),
        "no_candidate": (
            "This account isn't linked to an application yet. If you've applied, use the "
            "link in your confirmation email."
        ),
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user_in_groups(user):
            raise ValidationError(self.error_messages["staff_account"], code="staff_account")
        if getattr(user, "candidate", None) is None:
            raise ValidationError(self.error_messages["no_candidate"], code="no_candidate")
