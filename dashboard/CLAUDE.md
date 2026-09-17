# dashboard app

RBAC-secured, HTMX-filtered (`htmx.org` via CDN only, no JS framework).

## Access and scoping

`dashboard/rbac.py` `scoped_applications_queryset` is the single security
boundary that every queryset flows through:
- **Full access:** Recruiter, HR, Senior Reviewer, Leadership Manager,
  superuser.
- **Department-scoped:** Technical Interviewer. With no department, the
  dashboard shows an empty state, not a 403.
- **Nothing:** everyone else.

## Views

- **`DashboardView`:** the command center. It shows:
  - a greeting
  - KPI cards (including interviewing count and average CV score)
  - the pipeline funnel
  - the filterable application table
  - an attention rail built by `build_attention_rail`: upcoming and overdue
    interviews, recent feedback (needs `view_interviewfeedback`), unread
    notifications. The rail is scoped to the same applications.
- **`DashboardResultsView`:** the HTMX partial (`#dashboard-results`) that
  re-renders cards, pipeline and table. It doesn't rebuild the rail.
- **`DashboardExportView`:** streamed CSV of the same scoped and filtered
  rows, unpaginated.

## Implementation notes

- Cards, pipeline and table all come from the same scoped, filtered queryset.
- `services._status_counts` must clear ordering (`.order_by()`) before
  grouping, or counts collapse to 1 per stage.
- 28 tests in `dashboard/tests.py`. Rail scoping and pipeline regression
  tests are also in `accounts/test_layouts.py`.
