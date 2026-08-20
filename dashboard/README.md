# Recruitment Dashboard

An interactive, self-filtering dashboard for HR, Leadership, and reviewers
to monitor recruitment progress across all existing apps (`accounts`,
`candidates`, `positions`, `cv_screening`, `interviews`). No new models,
no changes to existing apps -- this is a read-only aggregation layer.

## 1. Architecture

```
dashboard/
  rbac.py        -- the ONLY place access scope is decided
  services.py    -- overview stats + pipeline counts (built on rbac's queryset)
  filters.py     -- department/position/status/score/category/search filters
  utils.py       -- score->category mapping, pagination helper
  views.py       -- DashboardAccessMixin, DashboardView, DashboardResultsView
  urls.py        -- app_name="dashboard"
  templates/dashboard/
    dashboard.html                -- full page: heading + filter form + results wrapper
    components/results.html       -- stats + pipeline + table (what HTMX swaps in)
    components/stats_cards.html
    components/pipeline.html
    components/candidate_table.html
  tests.py
```

`Application` is the anchor model -- it already links `Candidate`,
`Position`, and (via `position.screening_profile`) the CV screening
pipeline, so every dashboard query starts from `Application.objects`.

## 2. Query flow

```
rbac.scoped_applications_queryset(user)
        |  (RBAC applied here -- select_related on candidate/position/dept)
        v
services.annotate_latest_cv_result(queryset)
        |  (Subquery: attaches cv_score for (candidate, position.screening_profile))
        v
filters.apply_filters(queryset, request.GET)
        |  (department/position/status/search/score/category -- narrows only)
        v
utils.paginate(queryset, page, per_page=25)
        |
        v
render candidate_table.html
```

Stats (`services.get_overview_stats`) and the pipeline strip
(`services.get_pipeline_counts`) are computed from the **RBAC-scoped**
queryset directly (not the filtered one) -- they show the user's overall
recruitment picture; the table is the filterable/searchable detail view.

The overview cards deliberately only show the 3 numbers the pipeline
strip *doesn't* already cover (Total Candidates, Total Applications, Open
Positions). CV Screening / CV Screening Passed / CV Screening Failed /
Accepted / Rejected are stages in the 9-step pipeline strip below them --
repeating those same counts as separate KPI cards would just be the same
number shown twice. One place per number.

Query cost per page load: 1 query for the RBAC-scoped+annotated+filtered
page of applications (with `select_related` covering candidate,
candidate's department, position, position's department,
position's screening profile, and a correlated subquery for CV score --
no N+1), 1 `COUNT` for pagination, 2 small `COUNT`s for the overview
cards, 1 `GROUP BY status` for the pipeline. Five queries total
regardless of how many candidates exist.

## 3. RBAC enforcement

All of it lives in `dashboard/rbac.py`. Nothing else in the app re-derives
scope -- `services.py` and `filters.py` both start from
`scoped_applications_queryset(user)`.

| Group | Scope |
|---|---|
| Superuser | Everything |
| Recruiter | Everything |
| HR Interviewer | Everything |
| Senior Reviewer | Everything |
| Leadership Manager | Everything |
| Technical Interviewer | `candidate__department == user.profile.department` only |
| Technical Interviewer with no department | Empty result set + explanatory message (fails closed, not a 500) |
| Candidate / any other group | No dashboard access at all (403) |

View-level gate: `DashboardAccessMixin` in `views.py` subclasses the
existing `accounts.mixins.GroupRequiredMixin` (previously defined but
unused anywhere in the codebase) with one addition -- superusers bypass
the group check, since they have no group memberships by Django
convention but must always have full access. Nothing in
`accounts/mixins.py` was modified.

Filters (`filters.py`) run **on top of** the already-scoped queryset --
selecting another department in the filter UI as a Technical Interviewer
does not widen access, it just returns zero rows (covered by
`test_technical_interviewer_cannot_leak_other_department_via_filter`).

Known pre-existing gap, not introduced or fixed here: `cv_screening.view_cv`
has no permission check beyond `login_required`. The dashboard's "View CV
Result" link only appears for rows already inside the user's RBAC scope,
so the dashboard itself is not a new leak -- but the underlying endpoint
would still allow guessing another CV's URL directly. Worth a follow-up
outside this task.

## 4. Filter system

All filters are combinable (AND). Implemented by hand in `filters.py`
(no `django-filter` dependency -- the filter set is small enough that a
dependency wasn't justified).

- **Department** -- `candidate__department_id`
- **Position** -- `position_id`
- **Application Stage / Application Status** -- these are the same field
  in this data model (`Application.status`, using the existing 9-stage
  `STATUS_CHOICES`). One dropdown serves both.
- **CV Match Score range** -- `score_min`/`score_max`, whole percentages
  converted to the 0.0-1.0 stored range
- **Match Category** -- maps to the same score thresholds as
  `CVMatchResult.match_category()` (0.8 / 0.6 / 0.4), since category is a
  Python method, not a stored field
- **Search** -- candidate first/last name or email; multi-word queries
  (e.g. "Jane Doe") are split into terms, each term matched against any
  field, all terms required (so a full-name search works even though no
  single field contains the whole string)

All values are read from `request.GET`, validated defensively (e.g.
`.isdigit()`, a whitelist of valid status values, clamped score ranges) --
an invalid or malicious value is silently ignored rather than trusted or
raising a 500.

## 5. HTMX implementation

No `django-htmx` package -- `htmx.org` is loaded via CDN script tag in
`dashboard.html`'s `extra_head` block (doesn't affect any other page),
and the server just reads plain `request.GET` on every request, same as
a normal full-page load. No JavaScript was written.

- The filter `<form>` has `hx-get`, `hx-target="#dashboard-results"`,
  `hx-trigger="change, keyup changed delay:400ms from:input[type=search], submit"`,
  and `hx-push-url="true"` -- every dropdown change or a debounced search
  keystroke re-fetches `dashboard:dashboard-results` and swaps the
  results wrapper, and the URL updates so filtered views are bookmarkable
  and shareable.
- Pagination links inside the (already-swapped) table carry their own
  `hx-get` + `hx-include="#dashboard-filters"` so page 2+ requests still
  carry the active filters; HTMX automatically wires up `hx-*` attributes
  on newly-swapped content, no extra JS needed.
- `DashboardResultsView` and `DashboardView` share one context builder
  (`build_dashboard_context`) so the initial full-page load and every
  subsequent HTMX partial render identically -- they can't drift apart.

## 6. Testing instructions

```bash
python manage.py test dashboard
```

If your `DATABASE_URL` points at a remote Postgres instance without fast
local access, override it for the test run so Django uses local SQLite
instead (faster, and doesn't touch the real database at all):

```bash
DATABASE_URL="" python manage.py test dashboard
```

19 tests, grouped by the categories in the task spec:

- `AnonymousAccessTests` -- anonymous request never gets a 200
- `RBACTests` -- Recruiter sees both departments; Technical Interviewer
  sees only their own; a crafted `?department=` filter can't leak another
  department; a Technical Interviewer with no department gets the
  graceful empty state, not a crash; the `Candidate` group is denied
  entirely; superuser sees everything
- `FilterTests` -- department/status/position individually, combined
  filters intersect correctly, invalid filter values don't 500, search
  matches full names split across first/last name
- `CVIntegrationTests` -- score and match category appear correctly for
  a screened candidate; a candidate with no CV at all renders cleanly
  with `None`/`—` instead of crashing; score-range and category filters
  work
- `PaginationTests` -- page size is capped at 25; page 2 is reachable
  through the HTMX results endpoint

Run the full existing suite alongside it to confirm nothing else broke:

```bash
DATABASE_URL="" python manage.py test
```

## Reaching the dashboard

A "Dashboard" link was added to the shared nav in `templates/base.html`
(one line, additive) -- `/dashboard/` for anyone logged in and in an
allowed group.

## Known data gaps found during inspection (not fixed here)

- `tech01` (Technical Interviewer) currently has no department assigned
  in the real database -- they will see the graceful empty state until
  an admin assigns one via `/admin/`.
- `manager01` (Leadership Manager) has no `UserProfile` row at all --
  harmless for this dashboard since Leadership Manager has full
  system-wide access regardless of department, but worth knowing about.
