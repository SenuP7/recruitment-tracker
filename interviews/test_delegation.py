"""Interview ownership and delegation.

The properties being protected: responsibility only moves when the delegate
accepts, delegation is one hop, only the right people can act, everything is
audited, and the candidate never sees any of it.
"""

from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from io import StringIO

from accounts import audit, staff
from accounts.models import AuditEvent, Department, UserProfile
from candidates.models import Application, Candidate
from interviews import delegation
from interviews.models import Interview, InterviewDelegation, StaffNotification
from positions.models import Position

PASSWORD = "delegation-test-pw-4410"


def make_staff(username, *, roles=("HR Interviewer",), department=None):
    user = User.objects.create_user(username, email=f"{username}@example.com", password=PASSWORD)
    for role in roles:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
    UserProfile.objects.update_or_create(user=user, defaults={"department": department})
    return user


class DelegationBase(TestCase):
    def setUp(self):
        cache.clear()
        self.engineering = Department.objects.create(name="Engineering")
        self.design = Department.objects.create(name="Design")

        self.recruiter = make_staff("recruiter_d", roles=("Recruiter",), department=self.engineering)
        self.interviewer = make_staff("interviewer_d", department=self.engineering)
        self.colleague = make_staff("colleague_d", department=self.engineering)
        self.chief = make_staff("chief_d", roles=("Technical Interviewer", staff.DEPARTMENT_CHIEF_GROUP), department=self.engineering)
        self.outsider = make_staff("outsider_d", department=self.design)
        self.admin = make_staff("admin_d", roles=(staff.ADMIN_GROUP,))
        self.engineering.chiefs.add(self.chief)

        for user in (self.interviewer, self.colleague, self.chief, self.outsider, self.admin):
            user.user_permissions.add(Permission.objects.get(codename="view_interview"))
            user.user_permissions.add(Permission.objects.get(codename="change_interview"))

        position = Position.objects.create(
            title="Backend Engineer", description="APIs", department=self.engineering, is_open=True
        )
        candidate = Candidate.objects.create(
            first_name="Ada", last_name="Kore", email="ada.d@example.com", phone="1"
        )
        application = Application.objects.create(candidate=candidate, position=position)
        self.interview = Interview.objects.create(
            application=application,
            interview_type="Technical",
            scheduled_date=timezone.now() + timedelta(days=10),
            assigned_interviewer=self.interviewer,
            created_by=self.recruiter,
        )


class OwnershipTests(DelegationBase):
    def test_who_scheduled_and_who_conducts_are_separate(self):
        self.assertEqual(self.interview.created_by, self.recruiter)
        self.assertEqual(self.interview.assigned_interviewer, self.interviewer)
        self.assertEqual(self.interview.conducting_interviewer, self.interviewer)

    def test_a_pending_offer_does_not_move_responsibility(self):
        delegation.offer(self.interview, to_user=self.colleague, reason="On leave", actor=self.interviewer)
        self.assertEqual(
            self.interview.conducting_interviewer,
            self.interviewer,
            "an unanswered request is not cover",
        )

    def test_responsibility_moves_only_once_accepted(self):
        record = delegation.offer(self.interview, to_user=self.colleague, reason="On leave", actor=self.interviewer)
        delegation.accept(record, actor=self.colleague)
        self.assertEqual(self.interview.conducting_interviewer, self.colleague)

    def test_declining_returns_it_to_the_assigned_interviewer(self):
        record = delegation.offer(self.interview, to_user=self.colleague, reason="On leave", actor=self.interviewer)
        delegation.decline(record, actor=self.colleague, note="Double-booked")
        self.assertEqual(self.interview.conducting_interviewer, self.interviewer)
        self.assertEqual(self.interview.assigned_interviewer, self.interviewer)


class DelegationAuthorisationTests(DelegationBase):
    def test_the_assigned_interviewer_can_delegate(self):
        self.assertTrue(delegation.can_delegate(self.interviewer, self.interview))

    def test_a_chief_of_that_department_can_delegate(self):
        self.assertTrue(delegation.can_delegate(self.chief, self.interview))

    def test_an_administrator_can_delegate(self):
        self.assertTrue(delegation.can_delegate(self.admin, self.interview))

    def test_an_unrelated_colleague_cannot(self):
        self.assertFalse(delegation.can_delegate(self.colleague, self.interview))

    def test_the_page_refuses_someone_who_may_not_delegate(self):
        self.client.force_login(self.colleague)
        response = self.client.get(reverse("interview-delegate", args=[self.interview.pk]))
        self.assertEqual(response.status_code, 403)

    def test_posting_directly_is_refused_too(self):
        """Hiding the button would stop nobody."""
        self.client.force_login(self.colleague)
        response = self.client.post(
            reverse("interview-delegate", args=[self.interview.pk]),
            {"to_user": self.chief.pk, "reason": "trying it on"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(InterviewDelegation.objects.exists())

    def test_only_the_person_asked_can_accept(self):
        record = delegation.offer(self.interview, to_user=self.colleague, reason="On leave", actor=self.interviewer)
        self.client.force_login(self.outsider)
        response = self.client.post(reverse("delegation-respond", args=[record.pk]), {"action": "accept"})
        self.assertEqual(response.status_code, 403)
        record.refresh_from_db()
        self.assertEqual(record.status, InterviewDelegation.PENDING)

    def test_a_candidate_account_cannot_reach_delegation_at_all(self):
        candidate_user = User.objects.create_user("cand_user_d", password=PASSWORD)
        candidate_user.groups.add(Group.objects.get_or_create(name="Candidate")[0])
        Candidate.objects.create(
            first_name="C", last_name="D", email="cd@example.com", phone="1", user=candidate_user
        )
        self.client.force_login(candidate_user)
        response = self.client.get(reverse("interview-delegate", args=[self.interview.pk]))
        self.assertIn(response.status_code, (302, 403))


class DelegationWorkflowTests(DelegationBase):
    def test_offering_notifies_the_delegate_and_is_audited(self):
        self.client.force_login(self.interviewer)
        self.client.post(
            reverse("interview-delegate", args=[self.interview.pk]),
            {"to_user": self.chief.pk, "reason": "I'm on leave that week"},
        )

        record = InterviewDelegation.objects.get()
        self.assertEqual(record.status, InterviewDelegation.PENDING)
        self.assertTrue(StaffNotification.objects.filter(recipient=self.chief).exists())
        event = AuditEvent.objects.get(action=audit.DELEGATION_OFFERED)
        self.assertEqual(event.actor, self.interviewer)
        self.assertEqual(event.detail["to"], "chief_d")

    def test_a_reason_is_required(self):
        self.client.force_login(self.interviewer)
        response = self.client.post(
            reverse("interview-delegate", args=[self.interview.pk]),
            {"to_user": self.chief.pk, "reason": "   "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(InterviewDelegation.objects.exists())

    def test_accepting_notifies_the_person_who_asked(self):
        record = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)
        self.client.force_login(self.colleague)
        self.client.post(reverse("delegation-respond", args=[record.pk]), {"action": "accept"})

        record.refresh_from_db()
        self.assertEqual(record.status, InterviewDelegation.ACCEPTED)
        self.assertTrue(StaffNotification.objects.filter(recipient=self.interviewer).exists())
        self.assertTrue(AuditEvent.objects.filter(action=audit.DELEGATION_ACCEPTED).exists())

    def test_declining_requires_a_note(self):
        record = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)
        self.client.force_login(self.colleague)
        self.client.post(reverse("delegation-respond", args=[record.pk]), {"action": "decline", "note": ""})

        record.refresh_from_db()
        self.assertEqual(record.status, InterviewDelegation.PENDING)

    def test_a_delegate_cannot_pass_it_on_again(self):
        """One hop only: a chain makes 'who is turning up' unanswerable."""
        record = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)
        delegation.accept(record, actor=self.colleague)

        self.assertFalse(
            delegation.can_delegate(self.colleague, self.interview),
            "the delegate is not the assigned interviewer, so cannot delegate onward",
        )

    def test_a_second_offer_replaces_the_first(self):
        first = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)
        delegation.offer(self.interview, to_user=self.chief, reason="Better fit", actor=self.interviewer)

        first.refresh_from_db()
        self.assertEqual(first.status, InterviewDelegation.WITHDRAWN)
        self.assertEqual(
            InterviewDelegation.objects.filter(status=InterviewDelegation.PENDING).count(), 1
        )

    def test_the_person_who_asked_can_withdraw(self):
        record = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)
        self.client.force_login(self.interviewer)
        self.client.post(reverse("delegation-withdraw", args=[record.pk]))

        record.refresh_from_db()
        self.assertEqual(record.status, InterviewDelegation.WITHDRAWN)
        self.assertTrue(StaffNotification.objects.filter(recipient=self.colleague).exists())

    def test_cross_department_delegation_is_allowed_but_flagged(self):
        record = delegation.offer(self.interview, to_user=self.outsider, reason="Cover", actor=self.interviewer)
        self.assertTrue(record.crosses_departments)
        self.assertEqual(record.status, InterviewDelegation.PENDING)

    def test_chiefs_of_the_department_are_offered_first(self):
        people = delegation.eligible_delegates(self.interview, exclude_user=self.interviewer)
        self.assertEqual(people[0], self.chief)

    def test_candidates_are_never_eligible(self):
        candidate_user = User.objects.create_user("never_eligible", password=PASSWORD)
        candidate_user.groups.add(Group.objects.get_or_create(name="Candidate")[0])
        self.assertNotIn(candidate_user, delegation.eligible_delegates(self.interview))

    def test_a_deactivated_person_is_not_eligible(self):
        self.colleague.is_active = False
        self.colleague.save(update_fields=["is_active"])
        self.assertNotIn(self.colleague, delegation.eligible_delegates(self.interview))


class DelegationLifecycleTests(DelegationBase):
    def test_cancelling_the_interview_closes_an_open_delegation(self):
        record = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)
        self.interview.status = "Cancelled"
        self.interview.save(update_fields=["status"])
        delegation.close_for_interview(self.interview, actor=self.interviewer)

        record.refresh_from_db()
        self.assertEqual(record.status, InterviewDelegation.WITHDRAWN)

    def test_an_unanswered_offer_expires_close_to_the_interview(self):
        Interview.objects.filter(pk=self.interview.pk).update(
            scheduled_date=timezone.now() + timedelta(hours=12)
        )
        record = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)

        out = StringIO()
        call_command("expire_delegations", stdout=out)

        record.refresh_from_db()
        self.assertEqual(record.status, InterviewDelegation.EXPIRED)
        self.assertTrue(StaffNotification.objects.filter(recipient=self.interviewer).exists())
        self.assertTrue(AuditEvent.objects.filter(action=audit.DELEGATION_EXPIRED).exists())

    def test_an_offer_well_ahead_of_the_interview_is_left_alone(self):
        record = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)
        call_command("expire_delegations", stdout=StringIO())

        record.refresh_from_db()
        self.assertEqual(record.status, InterviewDelegation.PENDING)

    def test_an_accepted_delegation_is_not_expired(self):
        Interview.objects.filter(pk=self.interview.pk).update(
            scheduled_date=timezone.now() + timedelta(hours=12)
        )
        record = delegation.offer(self.interview, to_user=self.colleague, reason="Leave", actor=self.interviewer)
        delegation.accept(record, actor=self.colleague)

        call_command("expire_delegations", stdout=StringIO())

        record.refresh_from_db()
        self.assertEqual(record.status, InterviewDelegation.ACCEPTED)
