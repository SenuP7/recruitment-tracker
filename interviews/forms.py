from datetime import datetime

from django import forms
from django.utils import timezone

from .models import Interview


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
        fields = ["application", "interview_type", "scheduled_date", "scheduled_time", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
