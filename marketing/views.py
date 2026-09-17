from datetime import date

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.views.generic import TemplateView

from . import status

# One place to change the public contact details every page quotes.
CONTACTS = {
    "help": "help@candidflow.example",
    "privacy": "privacy@candidflow.example",
    "security": "security@candidflow.example",
}

LEGAL_UPDATED = date(2026, 9, 17)

# Pages listed in sitemap.xml, in footer order. The app itself is excluded
# (and disallowed in robots.txt) -- only the public site is indexable.
PUBLIC_PAGES = (
    "landing", "help", "status", "security", "privacy",
    "terms", "cookies", "accessibility", "candidate-notice",
)


class PublicPageMixin:
    """Context shared by every public page: contacts, the footer status dot,
    and which top-nav link is active."""

    nav_key = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["contacts"] = CONTACTS
        context["legal_updated"] = LEGAL_UPDATED
        context["nav_key"] = self.nav_key
        context["version"] = settings.CANDIDFLOW_VERSION
        context.setdefault("site_status", status.footer_status())
        return context


class PublicPageView(PublicPageMixin, TemplateView):
    pass


class StatusView(PublicPageView):
    template_name = "marketing/status.html"
    nav_key = "status"

    def get_context_data(self, **kwargs):
        report = status.run_checks()
        kwargs["report"] = report
        kwargs["site_status"] = {"state": report["state"], "label": report["label"]}
        return super().get_context_data(**kwargs)

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response["Cache-Control"] = "no-store"
        return response


APP_PATH_PREFIXES = (
    "/accounts/", "/admin/", "/candidates/", "/positions/",
    "/interviews/", "/cv-screening/", "/dashboard/", "/healthz/",
)


def robots_txt(request):
    lines = ["User-agent: *"]
    lines += [f"Disallow: {prefix}" for prefix in APP_PATH_PREFIXES]
    lines += ["", f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}", ""]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    urls = "".join(
        f"<url><loc>{request.build_absolute_uri(reverse(name))}</loc></url>"
        for name in PUBLIC_PAGES
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    )
    return HttpResponse(body, content_type="application/xml")


def security_txt(request):
    """RFC 9116. Expires must be under a year out -- bump it with the policy."""
    lines = [
        f"Contact: mailto:{CONTACTS['security']}",
        "Expires: 2027-09-16T00:00:00.000Z",
        "Preferred-Languages: en",
        f"Canonical: {request.build_absolute_uri(reverse('security-txt'))}",
        f"Policy: {request.build_absolute_uri(reverse('security'))}#report",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
