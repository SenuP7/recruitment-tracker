from unittest.mock import patch

from django.contrib.auth.models import Group, Permission, User
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Department
from positions.models import Position

from .models import Application, Candidate


class ApplicationStatusNotificationSignalTests(TestCase):
    """Covers notification-service test cases TC-09 (creation doesn't notify)
    and TC-10 (publish only fires after the transaction commits)."""

    def setUp(self):
        department = Department.objects.create(name="Engineering")
        self.position = Position.objects.create(
            title="Backend Engineer", department=department, is_open=True
        )
        self.candidate = Candidate.objects.create(
            first_name="Jane", last_name="Doe", email="jane@example.com", phone="0700000000"
        )

    @patch("candidates.signals.publish_event")
    def test_creating_application_does_not_publish(self, mock_publish):
        with self.captureOnCommitCallbacks(execute=True):
            Application.objects.create(candidate=self.candidate, position=self.position)
        mock_publish.assert_not_called()

    @patch("candidates.signals.publish_event")
    def test_status_change_publishes_after_commit(self, mock_publish):
        application = Application.objects.create(candidate=self.candidate, position=self.position)
        mock_publish.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            application.status = "HR Interview"
            application.save()

        mock_publish.assert_called_once()
        _, kwargs = mock_publish.call_args
        self.assertEqual(kwargs["context"]["old_status"], "Applied")
        self.assertEqual(kwargs["context"]["new_status"], "HR Interview")

    @patch("candidates.signals.publish_event")
    def test_status_change_does_not_publish_if_transaction_rolls_back(self, mock_publish):
        application = Application.objects.create(candidate=self.candidate, position=self.position)
        mock_publish.reset_mock()

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    application.status = "HR Interview"
                    application.save()
                    raise RuntimeError("simulated failure inside the same atomic block")
            except RuntimeError:
                pass

        self.assertEqual(callbacks, [])
        mock_publish.assert_not_called()

    @patch("candidates.signals.publish_event")
    def test_saving_without_status_change_does_not_publish(self, mock_publish):
        application = Application.objects.create(candidate=self.candidate, position=self.position)
        mock_publish.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            application.save()  # same status, no transition

        mock_publish.assert_not_called()


class ListViewPaginationTests(TestCase):
    """Both CandidateListView and ApplicationListView gained paginate_by=25
    (previously unpaginated). Covers: page 1 caps at 25, remainder lands on
    page 2, and the total count badge (page_obj.paginator.count) reflects
    ALL rows, not just the current page."""

    def setUp(self):
        department = Department.objects.create(name="Engineering")
        self.position = Position.objects.create(
            title="Backend Engineer", department=department, is_open=True
        )
        for i in range(30):
            Candidate.objects.create(
                first_name=f"Cand{i}", last_name="Test", email=f"cand{i}@example.com", phone="0"
            )

        group, _ = Group.objects.get_or_create(name="Recruiter")
        group.permissions.add(
            Permission.objects.get(codename="view_candidate"),
            Permission.objects.get(codename="view_application"),
        )
        self.user = User.objects.create_user("pagination_user", password="pass12345")
        self.user.groups.add(group)

    def test_candidate_list_page_1_has_25_and_correct_total(self):
        client = Client()
        client.login(username="pagination_user", password="pass12345")
        response = client.get(reverse("candidate-list"))

        self.assertEqual(len(response.context["candidates"]), 25)
        self.assertEqual(response.context["page_obj"].paginator.count, 30)
        self.assertTrue(response.context["page_obj"].has_next())

    def test_candidate_list_page_2_has_remainder(self):
        client = Client()
        client.login(username="pagination_user", password="pass12345")
        response = client.get(reverse("candidate-list"), {"page": 2})

        self.assertEqual(len(response.context["candidates"]), 5)
        self.assertFalse(response.context["page_obj"].has_next())

    def test_application_list_paginates(self):
        candidates = list(Candidate.objects.all()[:26])
        for candidate in candidates:
            Application.objects.create(candidate=candidate, position=self.position)

        client = Client()
        client.login(username="pagination_user", password="pass12345")
        response = client.get(reverse("application-list"))

        self.assertEqual(len(response.context["applications"]), 25)
        self.assertEqual(response.context["page_obj"].paginator.count, 26)


class FlashMessageTests(TestCase):
    """CandidateCreateView/DeleteView gained SuccessMessageMixin -- confirms
    the message is actually queued (not just that the view still works)."""

    def setUp(self):
        group, _ = Group.objects.get_or_create(name="Recruiter")
        group.permissions.add(
            Permission.objects.get(codename="add_candidate"),
            Permission.objects.get(codename="delete_candidate"),
        )
        self.user = User.objects.create_user("flash_user", password="pass12345")
        self.user.groups.add(group)

    def _messages(self, response):
        from django.contrib.messages import get_messages
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_create_candidate_shows_success_message(self):
        client = Client()
        client.login(username="flash_user", password="pass12345")
        response = client.post(reverse("candidate-create"), {
            "first_name": "Msg", "last_name": "Test", "email": "flash@example.com",
            "phone": "0700000000", "current_status": "Applied",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("Candidate created successfully.", self._messages(response))

    def test_delete_candidate_shows_success_message(self):
        candidate = Candidate.objects.create(
            first_name="ToDelete", last_name="X", email="todelete@example.com", phone="0"
        )
        client = Client()
        client.login(username="flash_user", password="pass12345")
        response = client.post(reverse("candidate-delete", kwargs={"pk": candidate.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertIn("Candidate deleted successfully.", self._messages(response))
