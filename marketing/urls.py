from django.urls import path

from . import careers, views
from .views import PublicPageView, StatusView


def page(route, name, nav_key=None):
    return path(
        route,
        PublicPageView.as_view(template_name=f"marketing/{name.replace('-', '_')}.html", nav_key=nav_key),
        name=name,
    )


urlpatterns = [
    page("", "landing"),
    path("careers/", careers.CareersListView.as_view(), name="careers"),
    path("careers/<int:pk>/", careers.CareersDetailView.as_view(), name="careers-detail"),
    path("careers/<int:pk>/apply/", careers.CareersApplyView.as_view(), name="careers-apply"),
    path("apply/confirm/<str:token>/", careers.ApplicationConfirmView.as_view(), name="application-confirm"),

    page("help/", "help", nav_key="help"),
    path("status/", StatusView.as_view(), name="status"),
    page("security/", "security", nav_key="security"),
    page("privacy/", "privacy", nav_key="privacy"),
    page("terms/", "terms"),
    page("cookies/", "cookies"),
    page("accessibility/", "accessibility"),
    page("candidate-notice/", "candidate-notice"),

    path("robots.txt", views.robots_txt, name="robots"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
    path(".well-known/security.txt", views.security_txt, name="security-txt"),
]
