import os
from datetime import date

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.views.generic import TemplateView

from . import status

# One place to change the public contact details every page quotes.
CONTACTS = {
    "help": os.environ.get("CANDIDFLOW_HELP_EMAIL", "help@candidflow.example"),
    "privacy": os.environ.get("CANDIDFLOW_PRIVACY_EMAIL", "privacy@candidflow.example"),
    "security": os.environ.get("CANDIDFLOW_SECURITY_EMAIL", "security@candidflow.example"),
}

LEGAL_UPDATED = date(2026, 9, 17)

# RFC 9116 requires an expiry under a year out. Bump this when it nears --
# marketing/tests.py fails once it's within 60 days, so it can't lapse quietly.
SECURITY_TXT_EXPIRES = date(2027, 9, 16)

# Pages listed in sitemap.xml, in footer order. The app itself is excluded
# (and disallowed in robots.txt) -- only the public site is indexable.
PUBLIC_PAGES = (
    "landing", "careers", "signup", "help", "status", "security", "privacy",
    "terms", "cookies", "accessibility", "candidate-notice",
)


def public_context(nav_key=None):
    """The bits every public page needs: contacts, the footer status dot, and
    which top-nav link is active. A function as well as a mixin, because the
    careers apply view is a plain View with no get_context_data chain."""
    return {
        "contacts": CONTACTS,
        "legal_updated": LEGAL_UPDATED,
        "nav_key": nav_key,
        "version": settings.CANDIDFLOW_VERSION,
        "site_status": status.footer_status(),
    }


class PublicPageMixin:
    nav_key = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for key, value in public_context(self.nav_key).items():
            context.setdefault(key, value)
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
        f"Expires: {SECURITY_TXT_EXPIRES:%Y-%m-%d}T00:00:00.000Z",
        "Preferred-Languages: en",
        f"Canonical: {request.build_absolute_uri(reverse('security-txt'))}",
        f"Policy: {request.build_absolute_uri(reverse('security'))}#report",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
