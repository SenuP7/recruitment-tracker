"""Staff account administration.

The requirements being protected here: every staff member has their own
account, roles are shared but logins are not, an administrator never learns
someone's password, and deactivating one person doesn't touch anyone else.
"""

from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import audit, staff
from accounts.models import AuditEvent, Department, StaffInvite, UserProfile

PASSWORD = "staff-admin-pw-55120"


def make_user(username, *, roles=(), password=PASSWORD, active=True):
    user = User.objects.create_user(username, email=f"{username}@example.com", password=password)
    user.is_active = active
    user.save(update_fields=["is_active"])
    for role in roles:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


class StaffAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin_one", roles=[staff.ADMIN_GROUP])

    def test_only_administrators_reach_the_staff_pages(self):
        for role in ("Recruiter", "HR Interviewer", "Leadership Manager", "Senior Reviewer"):
            with self.subTest(role=role):
                self.client.force_login(make_user(f"person_{role.replace(' ', '_')}", roles=[role]))
                self.assertEqual(self.client.get(reverse("staff-list")).status_code, 403)
                self.client.logout()

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("staff-list")).status_code, 200)

    def test_a_candidate_account_cannot_reach_them(self):
        candidate_user = make_user("candidate_person", roles=["Candidate"])
        self.client.force_login(candidate_user)
        response = self.client.get(reverse("staff-list"))
        self.assertIn(response.status_code, (302, 403))


class StaffCreationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin_two", roles=[staff.ADMIN_GROUP])
        self.department = Department.objects.create(name="Engineering")
        self.client.force_login(self.admin)
        patcher = mock.patch("accounts.staff.publish_event", return_value=True)
        self.publish = patcher.start()
        self.addCleanup(patcher.stop)

    def create(self, **overrides):
        data = {
            "first_name": "Nadia",
            "last_name": "Haddad",
            "email": "nadia@example.com",
            "job_title": "Recruiter",
            "department": self.department.pk,
            "roles": ["Recruiter"],
        }
        data.update(overrides)
        return self.client.post(reverse("staff-create"), data)

    def test_the_account_has_no_usable_password_until_the_person_sets_one(self):
        self.create()
        user = User.objects.get(username="nadia@example.com")

        self.assertFalse(user.has_usable_password(), "the administrator must not know the password")
        self.assertTrue(user.profile.must_change_password)
        self.assertTrue(StaffInvite.objects.filter(user=user).exists())

    def test_the_setup_link_is_emailed_and_carries_the_token(self):
        self.create()
        invite = StaffInvite.objects.get()
        context = self.publish.call_args.kwargs["context"]
        self.assertIn(invite.token, context["setup_url"])

    def test_the_email_address_is_the_username(self):
        self.create(email="Mixed.Case@Example.com")
        self.assertTrue(User.objects.filter(username="mixed.case@example.com").exists())

    def test_a_duplicate_address_is_refused(self):
        self.create()
        response = self.create()
        self.assertContains(response, "already exists")
        self.assertEqual(User.objects.filter(username="nadia@example.com").count(), 1)

    def test_creation_is_audited_with_the_administrator_who_did_it(self):
        self.create()
        event = AuditEvent.objects.get(action=audit.STAFF_CREATED)
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.detail["roles"], ["Recruiter"])

    def test_two_people_can_hold_the_same_role_with_separate_accounts(self):
        self.create(email="one@example.com")
        self.create(email="two@example.com")

        one = User.objects.get(username="one@example.com")
        two = User.objects.get(username="two@example.com")
        self.assertNotEqual(one.pk, two.pk)
        self.assertTrue(one.groups.filter(name="Recruiter").exists())
        self.assertTrue(two.groups.filter(name="Recruiter").exists())


class StaffInviteAcceptanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin_three", roles=[staff.ADMIN_GROUP])
        with mock.patch("accounts.staff.publish_event", return_value=True):
            self.user, self.invite = staff.create_staff_account(
                email="newbie@example.com",
                first_name="New",
                last_name="Person",
                roles=["Recruiter"],
                created_by=self.admin,
            )

    def accept(self, password="chosen-by-me-99120"):
        return self.client.post(
            reverse("staff-accept-invite", args=[self.invite.token]),
            {"new_password1": password, "new_password2": password},
        )

    def test_setting_a_password_signs_them_in_and_clears_the_flag(self):
        response = self.accept()
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertTrue(self.user.has_usable_password())
        self.assertFalse(self.user.profile.must_change_password)
        self.assertIn("_auth_user_id", self.client.session)

    def test_a_weak_password_is_refused(self):
        response = self.accept(password="short")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_a_used_link_stops_working(self):
        self.accept()
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("staff-accept-invite", args=[self.invite.token])).status_code, 404
        )

    def test_expired_and_unknown_links_look_identical(self):
        StaffInvite.objects.filter(pk=self.invite.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(
            self.client.get(reverse("staff-accept-invite", args=[self.invite.token])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("staff-accept-invite", args=["not-a-real-token"])).status_code, 404
        )

    def test_until_they_set_a_password_everything_else_redirects_them(self):
        """The forced change has to be unavoidable, not a per-view check."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:dashboard"))
        self.assertRedirects(response, reverse("password_reset"))


class StaffDeactivationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin_four", roles=[staff.ADMIN_GROUP])
        self.leaver = make_user("leaver", roles=["Recruiter"])
        self.colleague = make_user("colleague", roles=["Recruiter"])
        self.client.force_login(self.admin)

    def test_deactivating_blocks_sign_in_and_leaves_the_colleague_alone(self):
        self.client.post(reverse("staff-deactivate", args=[self.leaver.pk]), {"reason": "left"})

        self.leaver.refresh_from_db()
        self.colleague.refresh_from_db()
        self.assertFalse(self.leaver.is_active)
        self.assertTrue(self.colleague.is_active, "same role, different person, untouched")
        self.assertTrue(self.colleague.groups.filter(name="Recruiter").exists())

    def test_an_existing_session_stops_working_immediately(self):
        other = self.client_class()
        other.force_login(self.leaver)
        self.assertEqual(other.get(reverse("profile")).status_code, 200)

        self.client.post(reverse("staff-deactivate", args=[self.leaver.pk]), {"reason": "left"})

        response = other.get(reverse("profile"))
        self.assertEqual(response.status_code, 302, "their open session must stop working")

    def test_the_account_is_kept_not_deleted(self):
        self.client.post(reverse("staff-deactivate", args=[self.leaver.pk]), {"reason": "left"})
        self.assertTrue(User.objects.filter(pk=self.leaver.pk).exists())

    def test_deactivation_is_audited_with_the_reason(self):
        self.client.post(reverse("staff-deactivate", args=[self.leaver.pk]), {"reason": "left the company"})
        event = AuditEvent.objects.get(action=audit.STAFF_DEACTIVATED)
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.detail["reason"], "left the company")

    def test_an_administrator_cannot_deactivate_themselves(self):
        self.client.post(reverse("staff-deactivate", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_reactivating_restores_access(self):
        self.client.post(reverse("staff-deactivate", args=[self.leaver.pk]), {"reason": "left"})
        self.client.post(reverse("staff-reactivate", args=[self.leaver.pk]))
        self.leaver.refresh_from_db()
        self.assertTrue(self.leaver.is_active)


class StaffRoleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin_five", roles=[staff.ADMIN_GROUP])
        self.member = make_user("member", roles=["Recruiter"])
        self.client.force_login(self.admin)

    def test_roles_can_be_added_and_removed_and_each_change_is_audited(self):
        self.client.post(reverse("staff-roles", args=[self.member.pk]), {"roles": ["HR Interviewer", "Senior Reviewer"]})

        self.assertEqual(
            {g.name for g in self.member.groups.all()}, {"HR Interviewer", "Senior Reviewer"}
        )
        self.assertTrue(AuditEvent.objects.filter(action=audit.ROLE_ASSIGNED, detail__role="HR Interviewer").exists())
        self.assertTrue(AuditEvent.objects.filter(action=audit.ROLE_REMOVED, detail__role="Recruiter").exists())

    def test_one_person_can_hold_several_roles(self):
        self.client.post(reverse("staff-roles", args=[self.member.pk]), {"roles": ["Recruiter", "Department Chief"]})
        self.assertEqual({g.name for g in self.member.groups.all()}, {"Recruiter", "Department Chief"})

    def test_the_last_administrator_cannot_be_demoted(self):
        """Losing every administrator is unrecoverable without shell access."""
        self.client.post(reverse("staff-roles", args=[self.admin.pk]), {"roles": ["Recruiter"]})
        self.assertTrue(self.admin.groups.filter(name=staff.ADMIN_GROUP).exists())

    def test_an_administrator_can_be_demoted_when_another_one_exists(self):
        make_user("admin_six", roles=[staff.ADMIN_GROUP])
        self.client.post(reverse("staff-roles", args=[self.admin.pk]), {"roles": ["Recruiter"]})
        self.assertFalse(self.admin.groups.filter(name=staff.ADMIN_GROUP).exists())

    def test_the_candidate_role_cannot_be_granted_to_staff(self):
        self.client.post(reverse("staff-roles", args=[self.member.pk]), {"roles": ["Candidate", "Recruiter"]})
        self.assertFalse(self.member.groups.filter(name="Candidate").exists())


class SessionRevocationTests(TestCase):
    def test_signing_out_everywhere_ends_other_sessions(self):
        user = make_user("multi_session", roles=["Recruiter"])
        first = self.client_class()
        first.force_login(user)
        second = self.client_class()
        second.force_login(user)

        first.post(reverse("revoke-my-sessions"))

        self.assertEqual(second.get(reverse("profile")).status_code, 302)
        self.assertTrue(AuditEvent.objects.filter(action=audit.SESSIONS_REVOKED).exists())

    def test_staff_sessions_are_shorter_than_a_candidates(self):
        user = make_user("session_staff", roles=["Recruiter"])
        self.client.post(reverse("login"), {"username": "session_staff", "password": PASSWORD})
        self.assertEqual(self.client.session.get_expiry_age(), staff.STAFF_SESSION_SECONDS)
