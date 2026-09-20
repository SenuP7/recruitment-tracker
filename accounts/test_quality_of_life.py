"""The command palette endpoint and list CSV export.

Both are new ways to reach existing data, which is exactly the shape of
change that quietly widens access if nobody checks. These tests exist to
pin that they don't.
"""

from django.contrib.auth.models import Group, Permission, User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Department
from candidates.models import Application, Candidate
from positions.models import Position


class QuickSearchTests(TestCase):
    """The palette must never surface a record the page behind it refuses."""

    def setUp(self):
        self.department = Department.objects.create(name="Engineering")
        self.candidate = Candidate.objects.create(
            first_name="Marcus",
            last_name="Webb",
            email="marcus.webb@example.com",
            phone="0700",
            department=self.department,
        )
        self.position = Position.objects.create(
            title="Platform Engineer",
            description="x",
            department=self.department,
        )

        self.allowed = User.objects.create_user("palette_staff", password="pass12345")
        self.allowed.user_permissions.add(
            Permission.objects.get(codename="view_candidate"),
            Permission.objects.get(codename="view_position"),
        )
        self.blind = User.objects.create_user("palette_blind", password="pass12345")

        self.url = reverse("quick-search")

    def test_anonymous_is_redirected_to_sign_in(self):
        response = Client().get(self.url, {"q": "Marcus"})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_it_finds_records_the_user_may_see(self):
        client = Client()
        client.login(username="palette_staff", password="pass12345")

        results = client.get(self.url, {"q": "Marcus"}).json()["results"]

        self.assertTrue(any(r["label"] == "Marcus Webb" for r in results))

    def test_a_user_without_permissions_gets_nothing(self):
        # The Candidate group holds no permissions at all, so this is the
        # shape of request a candidate account would make.
        client = Client()
        client.login(username="palette_blind", password="pass12345")

        results = client.get(self.url, {"q": "Marcus"}).json()["results"]

        self.assertEqual(results, [])

    def test_an_empty_query_returns_nothing_rather_than_everything(self):
        client = Client()
        client.login(username="palette_staff", password="pass12345")

        self.assertEqual(client.get(self.url, {"q": "   "}).json()["results"], [])
        self.assertEqual(client.get(self.url).json()["results"], [])


class ListExportTests(TestCase):
    """An export that ignored the list's filters would be a quiet way round
    both the search and whatever scoping the view applies."""

    def setUp(self):
        self.department = Department.objects.create(name="Engineering")
        for first, last, email in [
            ("Marcus", "Webb", "marcus@example.com"),
            ("Ines", "Duarte", "ines@example.com"),
        ]:
            Candidate.objects.create(
                first_name=first,
                last_name=last,
                email=email,
                phone="0700",
                department=self.department,
            )
        # A name Excel would treat as a formula if it were written raw.
        Candidate.objects.create(
            first_name="=cmd",
            last_name="Injection",
            email="formula@example.com",
            phone="0700",
            department=self.department,
        )

        self.user = User.objects.create_user("export_staff", password="pass12345")
        self.user.user_permissions.add(Permission.objects.get(codename="view_candidate"))
        self.client = Client()
        self.client.login(username="export_staff", password="pass12345")
        self.url = reverse("candidate-list")

    def body(self, response):
        return response.content.decode()

    def test_export_returns_a_csv_attachment(self):
        response = self.client.get(self.url, {"export": "csv"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("candidates-", response["Content-Disposition"])

    def test_export_includes_a_header_row_and_the_records(self):
        body = self.body(self.client.get(self.url, {"export": "csv"}))

        self.assertIn("First name", body)
        self.assertIn("Marcus", body)
        self.assertIn("Ines", body)

    def test_export_obeys_the_search_the_user_is_looking_at(self):
        body = self.body(self.client.get(self.url, {"q": "Marcus", "export": "csv"}))

        self.assertIn("Marcus", body)
        self.assertNotIn("Ines", body)

    def test_a_value_that_looks_like_a_formula_is_neutralised(self):
        body = self.body(self.client.get(self.url, {"export": "csv"}))

        # Prefixed with an apostrophe so a spreadsheet treats it as text.
        self.assertIn("'=cmd", body)

    def test_without_permission_the_export_is_refused_like_the_page(self):
        nobody = User.objects.create_user("export_nobody", password="pass12345")
        client = Client()
        client.login(username="export_nobody", password="pass12345")

        response = client.get(self.url, {"export": "csv"})

        self.assertEqual(response.status_code, 403)


class DuplicateEmailMessageTests(TestCase):
    """Candidate.email is already unique. The improvement is that the refusal
    now says which record holds the address and links to it."""

    def setUp(self):
        self.department = Department.objects.create(name="Engineering")
        self.existing = Candidate.objects.create(
            first_name="Ines",
            last_name="Duarte",
            email="ines@example.com",
            phone="0700",
            department=self.department,
        )
        group, _ = Group.objects.get_or_create(name="Recruiter")
        group.permissions.add(
            Permission.objects.get(codename="add_candidate"),
            Permission.objects.get(codename="view_candidate"),
        )
        user = User.objects.create_user("dupe_staff", password="pass12345")
        user.groups.add(group)
        self.client = Client()
        self.client.login(username="dupe_staff", password="pass12345")

    def test_the_error_names_the_existing_candidate_and_links_to_it(self):
        response = self.client.post(
            reverse("candidate-create"),
            {
                "first_name": "Someone",
                "last_name": "Else",
                "email": "ines@example.com",
                "phone": "0700",
                "department": self.department.pk,
                "current_status": "Applied",
            },
        )

        self.assertEqual(response.status_code, 200)  # redisplayed, not saved
        body = response.content.decode()
        self.assertIn("Ines Duarte", body)
        self.assertIn(reverse("candidate-detail", args=[self.existing.pk]), body)
        self.assertEqual(Candidate.objects.filter(email="ines@example.com").count(), 1)
