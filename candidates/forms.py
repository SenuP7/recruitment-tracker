"""Forms for candidate records.

Django already refuses a duplicate email -- Candidate.email is unique -- but
the default message ("Candidate with this Email already exists.") leaves the
person on a dead end: they cannot see which record holds it or get to it.
"""

from django import forms
from django.urls import reverse
from django.utils.html import format_html

from .models import Candidate


CANDIDATE_FIELDS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "department",
    "current_status",
]


class CandidateForm(forms.ModelForm):
    class Meta:
        model = Candidate
        fields = CANDIDATE_FIELDS

    def clean_email(self):
        email = self.cleaned_data["email"]

        existing = Candidate.objects.filter(email__iexact=email)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        match = existing.first()

        if match is None:
            return email

        # format_html escapes the name, which is user-supplied.
        raise forms.ValidationError(
            format_html(
                'This address already belongs to {}. Open that record instead, '
                'or use a different address. <a href="{}">Go to {}</a>',
                str(match),
                reverse("candidate-detail", args=[match.pk]),
                str(match),
            )
        )
