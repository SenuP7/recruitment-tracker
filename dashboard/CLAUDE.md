# dashboard app

Built from scratch, RBAC-secured, HTMX-filtered (no new JS framework,
`htmx.org` via CDN only). `dashboard/rbac.py` is the single security
boundary all querysets flow through: Recruiter/HR/Senior Reviewer/
Leadership Manager/superuser get full access, Technical Interviewer is
department-scoped, everyone else gets nothing.

Overview cards + pipeline strip + table all derive from the same
RBAC-scoped-and-filtered queryset (they used to be frozen/unfiltered —
fixed). 23 tests.
