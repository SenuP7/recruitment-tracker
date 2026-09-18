"""Administrator screens for staff accounts.

Kept out of the Django admin on purpose: these actions (create, deactivate,
change roles) need to be audited and to follow the rules in accounts/staff.py,
and the Django admin would let a superuser bypass all of it silently.
"""

from django import forms
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from . import audit, staff
from .models import Department, StaffInvite, UserProfile


class AdministratorRequiredMixin(LoginRequiredMixin):
    """Only an Administrator (or a superuser) manages accounts. Deliberately
    not a model permission: this is about who runs the system, and Django's
    add_user/change_user permissions would also open the Django admin."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not staff.is_administrator(request.user):
            raise PermissionDenied("Only administrators can manage staff accounts.")
        return super().dispatch(request, *args, **kwargs)


class StaffAccountForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(
        help_text="Their work address. This is also the username they sign in with."
    )
    job_title = forms.CharField(max_length=120, required=False)
    department = forms.ModelChoiceField(
        queryset=Department.objects.order_by("name"), required=False
    )
    roles = forms.MultipleChoiceField(
        choices=[(role, role) for role in staff.ASSIGNABLE_ROLES],
        widget=forms.CheckboxSelectMultiple,
        help_text="Several people can hold the same role; each keeps their own account.",
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already exists for that address.")
        return email


class StaffListView(AdministratorRequiredMixin, ListView):
    template_name = "accounts/staff_list.html"
    context_object_name = "staff_members"
    paginate_by = 50

    def get_queryset(self):
        return staff.staff_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pending = {
            invite.user_id: invite
            for invite in StaffInvite.objects.filter(accepted_at__isnull=True, revoked_at__isnull=True)
        }
        # Built here rather than in the template: working out which checkbox
        # is ticked is a query question, not a presentation one.
        context["rows"] = [
            {
                "user": member,
                "roles": [
                    {"name": role, "held": role in {g.name for g in member.groups.all()}}
                    for role in staff.ASSIGNABLE_ROLES
                ],
                "invite_pending": member.pk in pending,
            }
            for member in context["staff_members"]
        ]
        return context


class StaffCreateView(AdministratorRequiredMixin, View):
    template_name = "accounts/staff_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": StaffAccountForm()})

    def post(self, request):
        form = StaffAccountForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        user, invite = staff.create_staff_account(
            email=form.cleaned_data["email"],
            first_name=form.cleaned_data["first_name"],
            last_name=form.cleaned_data["last_name"],
            roles=form.cleaned_data["roles"],
            department=form.cleaned_data["department"],
            job_title=form.cleaned_data["job_title"],
            created_by=request.user,
            request=request,
        )
        staff.send_staff_invite(request, invite)
        messages.success(
            request,
            f"Account created for {user.get_full_name() or user.username}. "
            "They've been emailed a link to set their own password.",
        )
        return redirect("staff-list")


class StaffRolesView(AdministratorRequiredMixin, View):
    """Changing someone's roles, which is the most sensitive thing on this
    page -- it can hand out or take away access to every candidate."""

    def post(self, request, pk):
        user = get_object_or_404(staff.staff_queryset(), pk=pk)
        roles = request.POST.getlist("roles")

        if staff.would_remove_last_administrator(user, roles):
            messages.error(
                request,
                "That would leave nobody able to administer the system. Give someone else "
                "the Administrator role first.",
            )
            return redirect("staff-list")

        staff.set_roles(user, roles, actor=request.user, request=request)
        messages.success(request, f"Roles updated for {user.get_full_name() or user.username}.")
        return redirect("staff-list")


class StaffDeactivateView(AdministratorRequiredMixin, View):
    template_name = "accounts/staff_confirm_deactivate.html"

    def get(self, request, pk):
        user = get_object_or_404(staff.staff_queryset(), pk=pk)
        return render(request, self.template_name, {"staff_member": user})

    def post(self, request, pk):
        user = get_object_or_404(staff.staff_queryset(), pk=pk)

        if user == request.user:
            messages.error(request, "You can't deactivate your own account.")
            return redirect("staff-list")
        if staff.would_remove_last_administrator(user, []):
            messages.error(request, "That would leave nobody able to administer the system.")
            return redirect("staff-list")

        staff.deactivate_staff(
            user, actor=request.user, request=request, reason=request.POST.get("reason", "")
        )
        messages.success(
            request,
            f"{user.get_full_name() or user.username} can no longer sign in, and their open "
            "sessions have been ended. Their past work and audit trail are untouched.",
        )
        return redirect("staff-list")


class StaffReactivateView(AdministratorRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(staff.staff_queryset(), pk=pk)
        staff.reactivate_staff(user, actor=request.user, request=request)
        messages.success(request, f"{user.get_full_name() or user.username} can sign in again.")
        return redirect("staff-list")


class StaffResendInviteView(AdministratorRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(staff.staff_queryset(), pk=pk)
        invite = StaffInvite.issue(user, created_by=request.user)
        staff.send_staff_invite(request, invite)
        messages.success(request, f"A new setup link has been sent to {invite.email}.")
        return redirect("staff-list")


class StaffAcceptInviteView(View):
    """Public: turns a setup link into a usable password.

    Expired, used, revoked and unknown tokens all render the same page, so the
    link can't be used to find out whether an account exists.
    """

    template_name = "accounts/staff_accept_invite.html"
    invalid_template = "accounts/staff_invite_invalid.html"

    def get_invite(self):
        return (
            StaffInvite.objects.filter(token=self.kwargs["token"]).select_related("user").first()
        )

    def get(self, request, *args, **kwargs):
        invite = self.get_invite()
        if invite is None or not invite.is_usable:
            return render(request, self.invalid_template, status=404)
        return render(request, self.template_name, {"invite": invite, "form": SetPasswordForm(user=invite.user)})

    def post(self, request, *args, **kwargs):
        invite = self.get_invite()
        if invite is None or not invite.is_usable:
            return render(request, self.invalid_template, status=404)

        form = SetPasswordForm(user=invite.user, data=request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"invite": invite, "form": form})

        form.save()
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])

        profile, _ = UserProfile.objects.get_or_create(user=invite.user)
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])

        audit.record(audit.PASSWORD_CHANGED, actor=invite.user, request=request, target=invite.user, via="setup link")
        login(request, invite.user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Your password is set. Welcome.")
        return redirect("post-login-redirect")


class RevokeMySessionsView(LoginRequiredMixin, View):
    """"Sign out everywhere", for a staff member who used a shared machine."""

    def post(self, request):
        user = request.user
        count = staff.revoke_sessions(user, actor=user, request=request, reason="signed out everywhere")
        messages.success(request, f"Signed out of {count} session{'' if count == 1 else 's'}.")
        return redirect("login")


class DepartmentListView(AdministratorRequiredMixin, ListView):
    """Departments and who chairs them.

    Chief is both a role and a fact about a department: the group carries the
    permissions, this page records which department each chief chairs. A
    person can chair more than one, and a department can have more than one
    chief -- deputies and shared leadership are normal.
    """

    template_name = "accounts/department_list.html"
    context_object_name = "departments"

    def get_queryset(self):
        return Department.objects.prefetch_related("chiefs").order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        eligible = (
            User.objects.filter(is_active=True, groups__name__in=staff.ASSIGNABLE_ROLES)
            .distinct()
            .order_by("first_name", "username")
        )
        context["rows"] = [
            {
                "department": department,
                "chiefs": list(department.chiefs.all()),
                "candidates_for_chief": [
                    {"user": person, "is_chief": person in department.chiefs.all()}
                    for person in eligible
                ],
            }
            for department in context["departments"]
        ]
        return context


class DepartmentChiefsView(AdministratorRequiredMixin, View):
    def post(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        chosen = User.objects.filter(
            pk__in=request.POST.getlist("chiefs"),
            is_active=True,
            groups__name__in=staff.ASSIGNABLE_ROLES,
        ).distinct()

        before = {user.pk for user in department.chiefs.all()}
        department.chiefs.set(chosen)
        after = {user.pk for user in chosen}

        # Chiefs need the role to go with the title, or the permission half of
        # "role plus a link on the department" would be missing.
        chief_group = Group.objects.get_or_create(name=staff.DEPARTMENT_CHIEF_GROUP)[0]
        for user in chosen:
            user.groups.add(chief_group)

        if before != after:
            audit.record(
                audit.ROLE_ASSIGNED,
                actor=request.user,
                request=request,
                target=department,
                role=staff.DEPARTMENT_CHIEF_GROUP,
                chiefs=[user.get_username() for user in chosen],
            )

        messages.success(request, f"Chiefs updated for {department.name}.")
        return redirect("department-list")
