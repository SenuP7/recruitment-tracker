from datetime import datetime

from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from accounts.decorators import RECRUITMENT_STAFF_GROUPS

from .models import Interview, InterviewFeedback


class InterviewForm(forms.ModelForm):
    """Splits the model's single scheduled_date DateTimeField into separate
    date and time inputs, then recombines them on save. The DB/model keep
    storing one DateTimeField -- only the form-level presentation changes."""

    scheduled_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={"invalid": "Please select a valid interview date."},
    )
    scheduled_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}),
        error_messages={"invalid": "Please select a valid interview time."},
    )

    class Meta:
        model = Interview
        fields = [
            "application", "interview_type", "scheduled_date", "scheduled_time",
            "status", "interviewer",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only recruitment staff can be assigned as an interviewer -- excludes
        # Candidate-group accounts and anyone in no recognized group.
        self.fields["interviewer"].queryset = User.objects.filter(
            Q(groups__name__in=RECRUITMENT_STAFF_GROUPS) | Q(is_superuser=True)
        ).distinct().order_by("username")
        self.fields["interviewer"].required = False

        if self.instance and self.instance.pk and self.instance.scheduled_date:
            local_dt = timezone.localtime(self.instance.scheduled_date)
            self.initial["scheduled_date"] = local_dt.date()
            self.initial["scheduled_time"] = local_dt.time()

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get("scheduled_date")
        time = cleaned_data.get("scheduled_time")

        if date and time:
            combined = timezone.make_aware(
                datetime.combine(date, time), timezone.get_current_timezone()
            )
            if combined < timezone.now():
                self.add_error(
                    "scheduled_date",
                    "Interview cannot be scheduled in the past.",
                )
            cleaned_data["scheduled_date"] = combined

        return cleaned_data

    def save(self, commit=True):
        self.instance.scheduled_date = self.cleaned_data["scheduled_date"]
        return super().save(commit=commit)


class FeedbackForm(forms.ModelForm):
    """Used for both root feedback and threaded replies. Pass is_reply=True to
    drop interview/rating/recommendation from the form -- a reply inherits its
    interview from the parent feedback and doesn't carry a rating or
    recommendation of its own; only rating is required, and only for root
    feedback (see clean())."""

    class Meta:
        model = InterviewFeedback
        fields = ["interview", "rating", "comments", "recommendation"]

    def __init__(self, *args, is_reply=False, **kwargs):
        self.is_reply = is_reply
        super().__init__(*args, **kwargs)
        if is_reply:
            for field_name in ("interview", "rating", "recommendation"):
                self.fields.pop(field_name, None)

    def clean(self):
        cleaned_data = super().clean()
        if not self.is_reply and cleaned_data.get("rating") is None:
            self.add_error("rating", "Rating is required for feedback (not required for replies).")
        return cleaned_data
