"""Public careers pages: browse open roles and apply without an account.

Applying creates no candidate and no application. It creates a
PendingApplication and emails a confirmation link; only that link turns the
submission into pipeline data (see candidates.applications).
"""

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView

from candidates.applications import (
    RATE_LIMITED_MESSAGE,
    confirm_pending_application,
    is_rate_limited,
    send_application_confirmation,
)
from candidates.models import PendingApplication
from cv_screening.uploads import validate_cv_file
from positions.models import Position

from .views import PublicPageMixin, public_context

MAX_MESSAGE_LENGTH = 2000


def open_positions():
    """Closed roles are never listed and never accept applications."""
    return Position.objects.filter(is_open=True).select_related("department")


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class CareersListView(PublicPageMixin, ListView):
    template_name = "marketing/careers_list.html"
    context_object_name = "positions"
    nav_key = "careers"
    paginate_by = 20

    def get_queryset(self):
        self.query = self.request.GET.get("q", "").strip()
        queryset = open_positions()
        if self.query:
            queryset = queryset.filter(
                Q(title__icontains=self.query) | Q(description__icontains=self.query)
            )
        return queryset.order_by("-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.query
        context["total_open"] = open_positions().count()
        return context


class CareersDetailView(PublicPageMixin, DetailView):
    template_name = "marketing/careers_detail.html"
    context_object_name = "position"
    nav_key = "careers"

    def get_queryset(self):
        return open_positions().select_related("screening_profile")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self.object.screening_profile
        context["required_skills"] = list(profile.required_skills.all()) if profile else []
        context["nice_skills"] = list(profile.nice_to_have_skills.all()) if profile else []
        context["other_positions"] = list(open_positions().exclude(pk=self.object.pk)[:3])
        return context


class CareersApplyView(View):
    """Takes a public application.

    Whether we already hold a candidate record for the address makes no
    difference to what this view renders, so the form can't be used to find
    out who has applied. Duplicate applications are detected later, at
    confirmation, when the person has proved the address is theirs.
    """

    template_name = "marketing/careers_apply.html"
    sent_template = "marketing/careers_apply_sent.html"

    def get_position(self):
        return get_object_or_404(open_positions(), pk=self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.page(self.get_position()))

    def post(self, request, *args, **kwargs):
        position = self.get_position()
        data = {
            field: request.POST.get(field, "").strip()
            for field in ("first_name", "last_name", "email", "phone", "message")
        }
        cv_file = request.FILES.get("cv_file")
        accepted = request.POST.get("accept_terms") == "on"

        errors = self.validate(data, cv_file, accepted)
        if errors:
            return render(request, self.template_name, self.page(position, data=data, errors=errors))

        if is_rate_limited(email=data["email"], ip_address=client_ip(request)):
            errors = {"form": RATE_LIMITED_MESSAGE}
            return render(request, self.template_name, self.page(position, data=data, errors=errors))

        pending = PendingApplication.start(
            position=position,
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            phone=data["phone"],
            message=data["message"],
            cv=cv_file,
            ip_address=client_ip(request),
        )
        send_application_confirmation(request, pending)

        return render(request, self.sent_template, self.page(position, email=data["email"]))

    def validate(self, data, cv_file, accepted):
        errors = {}
        if not data["first_name"]:
            errors["first_name"] = "Tell us your first name."
        if not data["last_name"]:
            errors["last_name"] = "Tell us your last name."
        email = data["email"]
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            errors["email"] = "Enter an email address we can reach you at."
        if len(data["message"]) > MAX_MESSAGE_LENGTH:
            errors["message"] = f"Please keep this under {MAX_MESSAGE_LENGTH} characters."
        cv_error = validate_cv_file(cv_file)
        if cv_error:
            errors["cv_file"] = cv_error
        if not accepted:
            errors["accept_terms"] = "Please confirm you've read how we use your data."
        return errors

    def page(self, position, data=None, errors=None, email=None):
        context = public_context("careers")
        context.update({
            "position": position,
            "data": data or {},
            "errors": errors or {},
            "email": email,
            "max_message_length": MAX_MESSAGE_LENGTH,
        })
        return context


class ApplicationConfirmView(View):
    """The emailed link: where a submission becomes a candidate record."""

    def get(self, request, *args, **kwargs):
        pending = (
            PendingApplication.objects.filter(token=self.kwargs["token"])
            .select_related("position")
            .first()
        )

        if pending is None or not pending.is_usable:
            return render(request, "marketing/apply_link_invalid.html", public_context("careers"), status=404)

        result = confirm_pending_application(pending)
        messages.success(request, result.message)

        if result.invite_token:
            return redirect("portal:accept-invite", token=result.invite_token)
        return redirect("login")
