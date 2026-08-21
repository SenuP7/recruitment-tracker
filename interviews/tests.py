import datetime

from django.contrib.auth.models import Group, Permission, User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department
from candidates.models import Application, Candidate
from positions.models import Position

from .forms import InterviewForm
from .models import Interview


class InterviewFormDateTimeSplitTests(TestCase):
    """Regression tests for splitting the single scheduled_date DateTimeField
    into separate date/time form inputs (QA-reported UX bug)."""

    def setUp(self):
        department = Department.objects.create(name="Engineering")
        position = Position.objects.create(
            title="Backend Engineer", department=department, is_open=True
        )
        candidate = Candidate.objects.create(
            first_name="Jane", last_name="Doe", email="jane@example.com", phone="0700000000"
        )
        self.application = Application.objects.create(
            candidate=candidate, position=position
        )

    def valid_data(self, date, time):
        return {
            "application": self.application.id,
            "interview_type": "HR",
            "scheduled_date": date,
            "scheduled_time": time,
            "status": "Scheduled",
        }

    def test_valid_future_date_and_time_combine_into_datetime(self):
        future = timezone.localdate() + datetime.timedelta(days=3)
        form = InterviewForm(data=self.valid_data(future, "14:30"))
        self.assertTrue(form.is_valid(), form.errors)

        interview = form.save()
        local_dt = timezone.localtime(interview.scheduled_date)
        self.assertEqual(local_dt.date(), future)
        self.assertEqual(local_dt.time(), datetime.time(14, 30))

    def test_missing_date_is_rejected(self):
        future = timezone.localdate() + datetime.timedelta(days=3)
        data = self.valid_data(future, "14:30")
        data["scheduled_date"] = ""
        form = InterviewForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("scheduled_date", form.errors)

    def test_missing_time_is_rejected(self):
        future = timezone.localdate() + datetime.timedelta(days=3)
        data = self.valid_data(future, "")
        form = InterviewForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("scheduled_time", form.errors)

    def test_past_datetime_is_rejected(self):
        past = timezone.localdate() - datetime.timedelta(days=1)
        form = InterviewForm(data=self.valid_data(past, "09:00"))
        self.assertFalse(form.is_valid())
        self.assertIn("scheduled_date", form.errors)

    def test_editing_existing_interview_prefills_split_fields(self):
        aware_dt = timezone.now() + datetime.timedelta(days=5)
        interview = Interview.objects.create(
            application=self.application,
            interview_type="Technical",
            scheduled_date=aware_dt,
            status="Scheduled",
        )
        form = InterviewForm(instance=interview)
        local_dt = timezone.localtime(aware_dt)
        self.assertEqual(form.initial["scheduled_date"], local_dt.date())
        self.assertEqual(form.initial["scheduled_time"], local_dt.time())


class InterviewCreateViewRBACTests(TestCase):
    """Confirms the split-field form works end-to-end for a role with
    add_interview permission, and that permission requirements are
    unchanged for everyone else."""

    def setUp(self):
        department = Department.objects.create(name="Engineering")
        position = Position.objects.create(
            title="Backend Engineer", department=department, is_open=True
        )
        candidate = Candidate.objects.create(
            first_name="Jane", last_name="Doe", email="jane@example.com", phone="0700000000"
        )
        self.application = Application.objects.create(
            candidate=candidate, position=position
        )

        self.recruiter_group, _ = Group.objects.get_or_create(name="Recruiter")
        self.recruiter_group.permissions.add(
            Permission.objects.get(codename="add_interview"),
            Permission.objects.get(codename="view_interview"),
        )
        self.recruiter = User.objects.create_user(
            "interview_recruiter", password="pass12345"
        )
        self.recruiter.groups.add(self.recruiter_group)

        self.candidate_group, _ = Group.objects.get_or_create(name="Candidate")
        self.candidate_user = User.objects.create_user(
            "interview_candidate", password="pass12345"
        )
        self.candidate_user.groups.add(self.candidate_group)

    def test_permitted_role_can_create_interview_with_split_fields(self):
        client = Client()
        client.login(username="interview_recruiter", password="pass12345")
        future = timezone.localdate() + datetime.timedelta(days=2)

        response = client.post(
            reverse("interview-create"),
            {
                "application": self.application.id,
                "interview_type": "HR",
                "scheduled_date": future,
                "scheduled_time": "09:30",
                "status": "Scheduled",
            },
        )
        self.assertRedirects(response, reverse("interview-list"))
        interview = Interview.objects.get(application=self.application)
        local_dt = timezone.localtime(interview.scheduled_date)
        self.assertEqual(local_dt.time(), datetime.time(9, 30))

    def test_unpermitted_role_still_denied_create(self):
        client = Client()
        client.login(username="interview_candidate", password="pass12345")
        response = client.get(reverse("interview-create"))
        self.assertEqual(response.status_code, 403)
