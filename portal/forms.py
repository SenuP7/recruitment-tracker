from django import forms
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User


class AcceptInviteForm(SetPasswordForm):
    """Django's password form (it applies the configured validators), used to
    set the first password on a brand-new, not-yet-saved candidate account."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Choose a password"
        self.fields["new_password2"].label = "Confirm password"


def email_is_available(email):
    """A candidate account uses the email address as its username, so an
    address already in use by any account can't be claimed again."""
    return not User.objects.filter(username__iexact=email).exists() and not User.objects.filter(
        email__iexact=email
    ).exists()


class CandidateCVUploadForm(forms.Form):
    cv_file = forms.FileField(label="CV file", help_text="PDF or DOCX, up to 5 MB.")
