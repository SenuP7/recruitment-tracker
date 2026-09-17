import datetime
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission, User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department
from candidates.models import Application, Candidate
from positions.models import Position

from .forms import InterviewForm
from .models import FeedbackAuditLog, Interview, InterviewFeedback, StaffNotification


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


class InterviewScheduledNotificationSignalTests(TestCase):
    """Covers notification-service test case: interview creation publishes
    an INTERVIEW_SCHEDULED event after commit; edits to an existing interview
    do not (only creation is a "scheduled" event)."""

    def setUp(self):
        department = Department.objects.create(name="Engineering")
        position = Position.objects.create(
            title="Backend Engineer", department=department, is_open=True
        )
        candidate = Candidate.objects.create(
            first_name="Jane", last_name="Doe", email="jane@example.com", phone="0700000000"
        )
        self.application = Application.objects.create(candidate=candidate, position=position)

    @patch("interviews.signals.publish_event")
    def test_creating_interview_publishes_after_commit(self, mock_publish):
        future = timezone.now() + datetime.timedelta(days=3)
        with self.captureOnCommitCallbacks(execute=True):
            Interview.objects.create(
                application=self.application,
                interview_type="HR",
                scheduled_date=future,
                status="Scheduled",
            )
        mock_publish.assert_called_once()
        _, kwargs = mock_publish.call_args
        self.assertEqual(kwargs["context"]["interview_type"], "HR")

    @patch("interviews.signals.publish_event")
    def test_editing_interview_does_not_publish(self, mock_publish):
        future = timezone.now() + datetime.timedelta(days=3)
        interview = Interview.objects.create(
            application=self.application,
            interview_type="HR",
            scheduled_date=future,
            status="Scheduled",
        )
        mock_publish.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            interview.status = "Completed"
            interview.save()

        mock_publish.assert_not_called()


class FeedbackTestBase(TestCase):
    """Shared fixtures for the feedback threading/authorization/audit tests
    below. Each subclass still defines its own users per the pattern already
    used elsewhere in this file (InterviewCreateViewRBACTests) -- kept here
    only because 6+ test classes would otherwise duplicate this same
    department/position/candidate/application/interview setup verbatim."""

    def setUp(self):
        department = Department.objects.create(name="Engineering")
        position = Position.objects.create(
            title="Backend Engineer", department=department, is_open=True
        )
        candidate = Candidate.objects.create(
            first_name="Jane", last_name="Doe", email="jane@example.com", phone="0700000000"
        )
        self.application = Application.objects.create(candidate=candidate, position=position)
        self.interview = Interview.objects.create(
            application=self.application,
            interview_type="HR",
            scheduled_date=timezone.now() + datetime.timedelta(days=1),
            status="Scheduled",
        )

    def make_user(self, username, group_name, permission_codenames=()):
        group, _ = Group.objects.get_or_create(name=group_name)
        for codename in permission_codenames:
            group.permissions.add(Permission.objects.get(codename=codename))
        user = User.objects.create_user(username, password="pass12345")
        user.groups.add(group)
        return user


class FeedbackCreationTests(FeedbackTestBase):
    """AC1 -- rating and comment both required, correctly linked to the
    submitting user and the chosen interview."""

    def setUp(self):
        super().setUp()
        self.author = self.make_user(
            "hr_author", "HR Interviewer", ["add_interviewfeedback", "view_interviewfeedback"]
        )

    def valid_data(self):
        return {
            "interview": self.interview.id,
            "rating": 4,
            "comments": "Strong communication skills.",
            "recommendation": "Pass",
        }

    def test_missing_rating_is_rejected(self):
        client = Client()
        client.login(username="hr_author", password="pass12345")
        data = self.valid_data()
        del data["rating"]
        response = client.post(reverse("feedback-create"), data)
        self.assertEqual(response.status_code, 200)  # re-rendered with form errors
        self.assertFalse(InterviewFeedback.objects.exists())

    def test_missing_comments_is_rejected(self):
        client = Client()
        client.login(username="hr_author", password="pass12345")
        data = self.valid_data()
        del data["comments"]
        response = client.post(reverse("feedback-create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(InterviewFeedback.objects.exists())

    def test_successful_creation_links_author_and_interview(self):
        client = Client()
        client.login(username="hr_author", password="pass12345")
        response = client.post(reverse("feedback-create"), self.valid_data())

        feedback = InterviewFeedback.objects.get()
        self.assertRedirects(
            response, reverse("feedback-thread", kwargs={"interview_pk": self.interview.id})
        )
        self.assertEqual(feedback.author, self.author)
        self.assertEqual(feedback.interview, self.interview)
        self.assertIsNone(feedback.parent)
        self.assertEqual(feedback.rating, 4)


class FeedbackThreadingTests(FeedbackTestBase):
    """AC2 -- replies nest under their parent (not a flat list), and don't
    require a rating."""

    def setUp(self):
        super().setUp()
        self.author = self.make_user(
            "hr_author", "HR Interviewer", ["add_interviewfeedback", "view_interviewfeedback"]
        )
        self.root = InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.author,
            rating=4,
            comments="Strong communication skills.",
            recommendation="Pass",
        )

    def test_reply_does_not_require_rating(self):
        client = Client()
        client.login(username="hr_author", password="pass12345")
        response = client.post(
            reverse("feedback-reply-create", kwargs={"pk": self.root.pk}),
            {"comments": "Agreed, especially in the system design round."},
        )
        self.assertEqual(response.status_code, 302)
        reply = InterviewFeedback.objects.get(parent=self.root)
        self.assertIsNone(reply.rating)
        self.assertEqual(reply.interview, self.interview)  # inherited from parent, not user-chosen

    def test_reply_is_nested_not_flattened(self):
        InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.author,
            parent=self.root,
            comments="Agreed, especially in the system design round.",
        )

        client = Client()
        client.login(username="hr_author", password="pass12345")
        response = client.get(
            reverse("feedback-thread", kwargs={"interview_pk": self.interview.id})
        )

        threads = list(response.context["feedback_threads"])
        self.assertEqual(len(threads), 1)  # exactly one ROOT entry, reply not flattened alongside it
        self.assertEqual(threads[0].pk, self.root.pk)
        self.assertEqual([r.comments for r in threads[0].replies.all()], [
            "Agreed, especially in the system design round."
        ])


class FeedbackEditAuthorizationTests(FeedbackTestBase):
    """AC3 -- only the author or an override-group member can edit."""

    def setUp(self):
        super().setUp()
        self.author = self.make_user("author_user", "HR Interviewer")
        self.other_staff = self.make_user("other_staff", "Recruiter")
        self.override_user = self.make_user("senior_reviewer", "Senior Reviewer")
        self.feedback = InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.author,
            rating=3,
            comments="Original comment.",
            recommendation="Hold",
        )

    def edit_url(self):
        return reverse("feedback-update", kwargs={"pk": self.feedback.pk})

    def edit_data(self, comments="Updated comment.", rating=3):
        return {
            "interview": self.interview.id,
            "rating": rating,
            "comments": comments,
            "recommendation": "Hold",
        }

    def test_non_author_non_override_user_is_denied(self):
        client = Client()
        client.login(username="other_staff", password="pass12345")
        response = client.post(self.edit_url(), self.edit_data())
        self.assertEqual(response.status_code, 403)
        self.feedback.refresh_from_db()
        self.assertEqual(self.feedback.comments, "Original comment.")

    def test_author_can_edit_own_feedback(self):
        client = Client()
        client.login(username="author_user", password="pass12345")
        response = client.post(self.edit_url(), self.edit_data(comments="Author's update."))
        self.assertEqual(response.status_code, 302)
        self.feedback.refresh_from_db()
        self.assertEqual(self.feedback.comments, "Author's update.")

    def test_override_group_member_can_edit_others_feedback(self):
        client = Client()
        client.login(username="senior_reviewer", password="pass12345")
        response = client.post(self.edit_url(), self.edit_data(comments="Reviewer override edit."))
        self.assertEqual(response.status_code, 302)
        self.feedback.refresh_from_db()
        self.assertEqual(self.feedback.comments, "Reviewer override edit.")


class FeedbackAuditLogTests(FeedbackTestBase):
    """AC4 -- an edit that changes rating/comments writes an audit log entry
    with the correct before/after values; an edit that changes nothing does
    not (there's nothing to audit)."""

    def setUp(self):
        super().setUp()
        self.author = self.make_user("author_user", "HR Interviewer")
        self.override_user = self.make_user("senior_reviewer", "Senior Reviewer")
        self.feedback = InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.author,
            rating=3,
            comments="Original comment.",
            recommendation="Hold",
        )

    def edit_url(self):
        return reverse("feedback-update", kwargs={"pk": self.feedback.pk})

    def test_edit_creates_audit_log_with_correct_diff(self):
        client = Client()
        client.login(username="author_user", password="pass12345")
        client.post(
            self.edit_url(),
            {
                "interview": self.interview.id,
                "rating": 5,
                "comments": "Revised after follow-up.",
                "recommendation": "Pass",
            },
        )

        entry = FeedbackAuditLog.objects.get(feedback=self.feedback)
        self.assertEqual(entry.changed_by, self.author)
        self.assertEqual(entry.diff["rating"], {"old": 3, "new": 5})
        self.assertEqual(
            entry.diff["comments"], {"old": "Original comment.", "new": "Revised after follow-up."}
        )

    def test_edit_by_override_role_also_creates_audit_log(self):
        """AC4: 'including edits by admins/authorized roles' -- the override
        role's edit must be audited too, not treated specially."""
        client = Client()
        client.login(username="senior_reviewer", password="pass12345")
        client.post(
            self.edit_url(),
            {
                "interview": self.interview.id,
                "rating": 1,
                "comments": "Escalation review.",
                "recommendation": "Reject",
            },
        )

        entry = FeedbackAuditLog.objects.get(feedback=self.feedback)
        self.assertEqual(entry.changed_by, self.override_user)

    def test_edit_with_no_actual_change_does_not_create_audit_log(self):
        client = Client()
        client.login(username="author_user", password="pass12345")
        client.post(
            self.edit_url(),
            {
                "interview": self.interview.id,
                "rating": 3,
                "comments": "Original comment.",
                "recommendation": "Hold",
            },
        )
        self.assertFalse(FeedbackAuditLog.objects.exists())


class FeedbackCreationPermissionExpansionTests(FeedbackTestBase):
    """Senior Reviewer was granted add_interviewfeedback alongside HR/Technical
    Interviewer -- confirms the permission grant actually works end-to-end,
    not just that it exists in the DB."""

    def setUp(self):
        super().setUp()
        self.reviewer = self.make_user(
            "senior_reviewer", "Senior Reviewer", ["add_interviewfeedback", "view_interviewfeedback"]
        )

    def test_senior_reviewer_can_create_feedback(self):
        client = Client()
        client.login(username="senior_reviewer", password="pass12345")
        response = client.post(
            reverse("feedback-create"),
            {
                "interview": self.interview.id,
                "rating": 5,
                "comments": "Reviewed independently.",
                "recommendation": "Pass",
            },
        )
        self.assertEqual(response.status_code, 302)
        feedback = InterviewFeedback.objects.get()
        self.assertEqual(feedback.author, self.reviewer)


class FeedbackDeletionTests(FeedbackTestBase):
    """Delete uses the same author-or-override authorization as edit, and
    every successful delete writes a DELETED FeedbackAuditLog entry that
    survives the deletion itself (feedback FK is SET_NULL, not CASCADE)."""

    def setUp(self):
        super().setUp()
        self.author = self.make_user(
            "author_user", "HR Interviewer", ["delete_interviewfeedback"]
        )
        self.other_staff = self.make_user(
            "other_staff", "Technical Interviewer", ["delete_interviewfeedback"]
        )
        self.override_user = self.make_user(
            "senior_reviewer", "Senior Reviewer", ["delete_interviewfeedback"]
        )
        self.feedback = InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.author,
            rating=3,
            comments="Original comment.",
            recommendation="Hold",
        )

    def delete_url(self, pk=None):
        return reverse("feedback-delete", kwargs={"pk": pk or self.feedback.pk})

    def test_non_author_non_override_user_is_denied(self):
        client = Client()
        client.login(username="other_staff", password="pass12345")
        response = client.post(self.delete_url())
        self.assertEqual(response.status_code, 403)
        self.assertTrue(InterviewFeedback.objects.filter(pk=self.feedback.pk).exists())

    def test_author_can_delete_own_feedback(self):
        client = Client()
        client.login(username="author_user", password="pass12345")
        response = client.post(self.delete_url())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(InterviewFeedback.objects.filter(pk=self.feedback.pk).exists())

    def test_override_group_member_can_delete_others_feedback(self):
        client = Client()
        client.login(username="senior_reviewer", password="pass12345")
        response = client.post(self.delete_url())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(InterviewFeedback.objects.filter(pk=self.feedback.pk).exists())

    def test_delete_creates_audit_log_that_survives_the_deletion(self):
        client = Client()
        client.login(username="author_user", password="pass12345")
        client.post(self.delete_url())

        entry = FeedbackAuditLog.objects.get(action="DELETED")
        self.assertIsNone(entry.feedback)  # SET_NULL -- row is gone, entry isn't
        self.assertEqual(entry.interview, self.interview)  # snapshot survives
        self.assertEqual(entry.changed_by, self.author)
        self.assertEqual(entry.diff["comments"]["old"], "Original comment.")
        self.assertIsNone(entry.diff["comments"]["new"])

    def test_prior_edit_audit_entries_also_survive_deletion(self):
        FeedbackAuditLog.objects.create(
            feedback=self.feedback,
            interview=self.interview,
            action="EDITED",
            changed_by=self.author,
            diff={"comments": {"old": "x", "new": "Original comment."}},
        )

        client = Client()
        client.login(username="author_user", password="pass12345")
        client.post(self.delete_url())

        self.assertEqual(FeedbackAuditLog.objects.count(), 2)  # EDITED + DELETED
        self.assertTrue(all(e.feedback_id is None for e in FeedbackAuditLog.objects.all()))

    def test_deleting_root_feedback_cascades_to_its_replies(self):
        reply = InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.author,
            parent=self.feedback,
            comments="A reply.",
        )
        client = Client()
        client.login(username="author_user", password="pass12345")
        client.post(self.delete_url())

        self.assertFalse(InterviewFeedback.objects.filter(pk=reply.pk).exists())


class StaffNotificationTriggerTests(FeedbackTestBase):
    """A feedback's author gets notified when someone ELSE edits/deletes it;
    never when they act on their own feedback."""

    def setUp(self):
        super().setUp()
        self.author = self.make_user(
            "author_user", "HR Interviewer", ["delete_interviewfeedback"]
        )
        self.other_staff = self.make_user(
            "senior_reviewer", "Senior Reviewer", ["delete_interviewfeedback"]
        )
        self.feedback = InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.author,
            rating=3,
            comments="Original comment.",
            recommendation="Hold",
        )

    def edit_url(self):
        return reverse("feedback-update", kwargs={"pk": self.feedback.pk})

    def delete_url(self):
        return reverse("feedback-delete", kwargs={"pk": self.feedback.pk})

    def test_edit_by_someone_else_notifies_the_author(self):
        client = Client()
        client.login(username="senior_reviewer", password="pass12345")
        client.post(
            self.edit_url(),
            {
                "interview": self.interview.id,
                "rating": 5,
                "comments": "Amended.",
                "recommendation": "Pass",
            },
        )
        notification = StaffNotification.objects.get()
        self.assertEqual(notification.recipient, self.author)
        self.assertIn("senior_reviewer", notification.message)
        self.assertIn("edited", notification.message)

    def test_editing_own_feedback_does_not_self_notify(self):
        client = Client()
        client.login(username="author_user", password="pass12345")
        client.post(
            self.edit_url(),
            {
                "interview": self.interview.id,
                "rating": 5,
                "comments": "Self-amended.",
                "recommendation": "Pass",
            },
        )
        self.assertFalse(StaffNotification.objects.exists())

    def test_delete_by_someone_else_notifies_the_author(self):
        client = Client()
        client.login(username="senior_reviewer", password="pass12345")
        client.post(self.delete_url())

        notification = StaffNotification.objects.get()
        self.assertEqual(notification.recipient, self.author)
        self.assertIn("deleted", notification.message)


class StaffNotificationListViewTests(FeedbackTestBase):
    """Users only see their own notifications, and viewing the list marks
    them read (reflected in the unread-count context processor)."""

    def setUp(self):
        super().setUp()
        self.user_a = self.make_user("user_a", "HR Interviewer", ["view_interview"])
        self.user_b = self.make_user("user_b", "HR Interviewer", ["view_interview"])
        StaffNotification.objects.create(recipient=self.user_a, message="For A", link="/x/")
        StaffNotification.objects.create(recipient=self.user_b, message="For B", link="/y/")

    def test_user_only_sees_their_own_notifications(self):
        client = Client()
        client.login(username="user_a", password="pass12345")
        response = client.get(reverse("staff-notifications"))
        messages = [n.message for n in response.context["notifications"]]
        self.assertEqual(messages, ["For A"])

    def test_unread_count_context_processor(self):
        client = Client()
        client.login(username="user_a", password="pass12345")

        response = client.get(reverse("interview-list"))
        self.assertEqual(response.context["unread_staff_notification_count"], 1)

    def test_viewing_list_marks_notifications_read(self):
        client = Client()
        client.login(username="user_a", password="pass12345")
        client.get(reverse("staff-notifications"))

        response = client.get(reverse("interview-list"))
        self.assertEqual(response.context["unread_staff_notification_count"], 0)

    def test_anonymous_user_sees_zero_unread_count(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from .context_processors import staff_notifications

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        self.assertEqual(staff_notifications(request), {"unread_staff_notification_count": 0})


class InterviewListPaginationTests(FeedbackTestBase):
    """InterviewListView gained paginate_by=25 (previously unpaginated)."""

    def setUp(self):
        super().setUp()
        for _ in range(24):  # + self.interview from FeedbackTestBase.setUp = 25
            Interview.objects.create(
                application=self.application,
                interview_type="HR",
                scheduled_date=timezone.now() + datetime.timedelta(days=1),
                status="Scheduled",
            )
        self.user = self.make_user("pagination_user", "Recruiter", ["view_interview"])

    def test_page_1_has_25_and_correct_total(self):
        client = Client()
        client.login(username="pagination_user", password="pass12345")
        response = client.get(reverse("interview-list"))

        self.assertEqual(len(response.context["interviews"]), 25)
        self.assertEqual(response.context["page_obj"].paginator.count, 25)
        self.assertFalse(response.context["page_obj"].has_next())

    def test_page_2_of_26_has_remainder(self):
        Interview.objects.create(
            application=self.application,
            interview_type="Technical",
            scheduled_date=timezone.now() + datetime.timedelta(days=1),
            status="Scheduled",
        )
        client = Client()
        client.login(username="pagination_user", password="pass12345")
        response = client.get(reverse("interview-list"), {"page": 2})

        self.assertEqual(len(response.context["interviews"]), 1)


class FeedbackFlashMessageTests(FeedbackTestBase):
    """InterviewFeedbackUpdateView/DeleteView both gained SuccessMessageMixin
    on top of already-custom form_valid() overrides (audit logging, staff
    notifications) -- confirms the message fires WITHOUT breaking that
    existing behavior, not instead of it."""

    def setUp(self):
        super().setUp()
        self.author = self.make_user(
            "author_user", "HR Interviewer", ["delete_interviewfeedback"]
        )
        self.feedback = InterviewFeedback.objects.create(
            interview=self.interview,
            author=self.author,
            rating=3,
            comments="Original comment.",
            recommendation="Hold",
        )

    def _messages(self, response):
        from django.contrib.messages import get_messages
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_edit_shows_message_and_still_creates_audit_log(self):
        client = Client()
        client.login(username="author_user", password="pass12345")
        response = client.post(
            reverse("feedback-update", kwargs={"pk": self.feedback.pk}),
            {
                "interview": self.interview.id,
                "rating": 5,
                "comments": "Amended.",
                "recommendation": "Pass",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("Feedback updated successfully.", self._messages(response))
        self.assertTrue(FeedbackAuditLog.objects.filter(action="EDITED").exists())

    def test_delete_shows_message_and_still_creates_audit_log(self):
        client = Client()
        client.login(username="author_user", password="pass12345")
        response = client.post(reverse("feedback-delete", kwargs={"pk": self.feedback.pk}))

        self.assertEqual(response.status_code, 302)
        self.assertIn("Feedback deleted successfully.", self._messages(response))
        self.assertTrue(FeedbackAuditLog.objects.filter(action="DELETED").exists())


class MyInterviewsViewTests(FeedbackTestBase):
    """MyInterviewsListView scopes to interviewer=request.user; existing
    interviews with no interviewer assigned show up for nobody."""

    def setUp(self):
        super().setUp()
        self.interviewer_a = self.make_user("interviewer_a", "Technical Interviewer", ["view_interview"])
        self.interviewer_b = self.make_user("interviewer_b", "Technical Interviewer", ["view_interview"])

        self.interview.interviewer = self.interviewer_a
        self.interview.save()

        Interview.objects.create(
            application=self.application,
            interview_type="Technical",
            scheduled_date=timezone.now() + datetime.timedelta(days=2),
            status="Scheduled",
            interviewer=self.interviewer_b,
        )
        Interview.objects.create(
            application=self.application,
            interview_type="HR",
            scheduled_date=timezone.now() + datetime.timedelta(days=3),
            status="Scheduled",
            # unassigned
        )

    def test_only_shows_own_assigned_interviews(self):
        client = Client()
        client.login(username="interviewer_a", password="pass12345")
        response = client.get(reverse("my-interviews"))

        interviews = response.context["interviews"]
        self.assertEqual(len(interviews), 1)
        self.assertEqual(interviews[0].pk, self.interview.pk)

    def test_unassigned_interviews_show_for_nobody(self):
        client = Client()
        client.login(username="interviewer_b", password="pass12345")
        response = client.get(reverse("my-interviews"))

        interviews = response.context["interviews"]
        self.assertEqual(len(interviews), 1)
        self.assertEqual(interviews[0].interviewer, self.interviewer_b)

    def test_different_user_sees_zero(self):
        other = self.make_user("uninvolved", "Recruiter", ["view_interview"])
        client = Client()
        client.login(username="uninvolved", password="pass12345")
        response = client.get(reverse("my-interviews"))

        self.assertEqual(len(response.context["interviews"]), 0)


class InterviewerAssignmentFormTests(FeedbackTestBase):
    """InterviewForm's interviewer field is optional and its queryset is
    restricted to RECRUITMENT_STAFF_GROUPS members + superusers."""

    def setUp(self):
        super().setUp()
        self.staff_user = self.make_user("staff_candidate_for_dropdown", "HR Interviewer")
        self.candidate_group_user = self.make_user("candidate_login", "Candidate")
        self.superuser = User.objects.create_superuser("super_dropdown", password="pass12345")

    def test_dropdown_includes_staff_and_superuser_excludes_candidate_group(self):
        from .forms import InterviewForm

        form = InterviewForm()
        queryset_usernames = set(form.fields["interviewer"].queryset.values_list("username", flat=True))

        self.assertIn("staff_candidate_for_dropdown", queryset_usernames)
        self.assertIn("super_dropdown", queryset_usernames)
        self.assertNotIn("candidate_login", queryset_usernames)

    def test_interviewer_field_is_optional(self):
        from .forms import InterviewForm

        future = timezone.localdate() + datetime.timedelta(days=3)
        form = InterviewForm(data={
            "application": self.application.id,
            "interview_type": "HR",
            "scheduled_date": future,
            "scheduled_time": "14:30",
            "status": "Scheduled",
            # interviewer omitted entirely
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_creating_interview_with_interviewer_persists_it(self):
        recruiter = self.make_user("recruiter_scheduler", "Recruiter", ["add_interview", "view_interview"])
        client = Client()
        client.login(username="recruiter_scheduler", password="pass12345")
        future = timezone.localdate() + datetime.timedelta(days=3)

        response = client.post(reverse("interview-create"), {
            "application": self.application.id,
            "interview_type": "HR",
            "scheduled_date": future,
            "scheduled_time": "09:30",
            "status": "Scheduled",
            "interviewer": self.staff_user.id,
        })
        self.assertEqual(response.status_code, 302)
        interview = Interview.objects.exclude(pk=self.interview.pk).get()
        self.assertEqual(interview.interviewer, self.staff_user)
