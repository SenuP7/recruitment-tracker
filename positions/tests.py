from django.contrib.auth.models import Group, Permission, User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Department

from .models import Position


class PositionListPaginationTests(TestCase):
    """PositionListView gained paginate_by=25 (previously unpaginated) --
    confirms page 1 caps at 25, the is_open=True filter is preserved
    alongside pagination, and the count badge reflects the true total."""

    def setUp(self):
        department = Department.objects.create(name="Engineering")
        for i in range(27):
            Position.objects.create(
                title=f"Role {i}", department=department, is_open=True
            )
        Position.objects.create(title="Closed Role", department=department, is_open=False)

        group, _ = Group.objects.get_or_create(name="Recruiter")
        group.permissions.add(Permission.objects.get(codename="view_position"))
        self.user = User.objects.create_user("pagination_user", password="pass12345")
        self.user.groups.add(group)

    def test_page_1_has_25_open_positions_only(self):
        client = Client()
        client.login(username="pagination_user", password="pass12345")
        response = client.get(reverse("position-list"))

        self.assertEqual(len(response.context["positions"]), 25)
        # 27 open positions total -- the closed one must never be counted/shown.
        self.assertEqual(response.context["page_obj"].paginator.count, 27)
        self.assertTrue(all(p.is_open for p in response.context["positions"]))

    def test_page_2_has_remainder(self):
        client = Client()
        client.login(username="pagination_user", password="pass12345")
        response = client.get(reverse("position-list"), {"page": 2})

        self.assertEqual(len(response.context["positions"]), 2)
