# Candidflow (recruitment tracker) — session notes

Internal Django 5.0 recruitment tracker, branded **Candidflow**. Server-rendered
class-based views + ModelForms + templates, HTMX on the dashboard only. No
DRF/API layer.

Six roles via Django Groups: Recruiter, HR Interviewer, Technical Interviewer,
Senior Reviewer, Leadership Manager, Candidate.

Apps:
- `accounts`: login/logout, profile, global search, shared mixins, the list toolbar, `ui` template tags
- `candidates`: candidates and applications
- `positions`
- `cv_screening`: CV upload, match scoring, results
- `interviews`: interviews, threaded feedback, audit log, staff notifications
- `dashboard`: see `dashboard/CLAUDE.md`
- `marketing`: the public site (see Public site below)
- `notifications`: stub, no views/urls; unused

Outside Django:
- `notification_client/`: publishes email events
- `notification-service/`: AWS SAM app; see its README

## Commit message convention

**Never add `Co-Authored-By` or `Claude-Session` trailers to commits.** User
preference, stated explicitly — plain descriptive commit messages only.
Only commit when the user asks.

## Working rules

- **Ask before major changes.** Any behavior change (especially access
  restrictions) needs the user's explicit approval first. Flag it, don't
  just do it.
- **UI work:** give options, mark the recommended one, and say which
  suggestions are opinion.

## Testing and dev servers

- Use `DATABASE_URL="" python manage.py test`. The real `DATABASE_URL`
  points at a remote Postgres that hangs trying to create a test database
  there. The empty override falls back to local SQLite.
- The empty override doesn't select SQLite by parsing a URL: the mere
  presence of a `DATABASE_URL` value picks the Postgres branch, which reads
  its connection details from `DB_*` (see `.env.example`).
- Current suite: **171 tests, all passing** (2026-09-17).
- The notification Lambda has its own pytest suite in
  `notification-service/tests`.
- The user runs their own server on **port 8000** against the real Postgres.
  Never start anything on 8000.
- Verification servers go on **8001** with `DATABASE_URL=""`. Stop them as
  soon as you're done. A stray SQLite server on 8000 once broke the user's
  logins.
- A `--noreload` server caches templates and Python, so restart it after
  changes.
- A SQLite-backed server can't see real accounts. Create a throwaway
  `__*_check__` user for browser checks and delete it afterwards.

## Access control

Groups and their permissions are managed **by hand** in the database (via
admin or shell), never via migration or fixture. The database is the source
of truth, so check it directly before assuming:

```python
from django.contrib.auth.models import Group
for g in Group.objects.all():
    print(g.name, [f'{p.content_type.app_label}.{p.codename}' for p in g.permissions.all()])
```

- **CRUD views** use `PermissionRequiredMixin(raise_exception=True)`, which
  returns 403.
- **Staff-only areas** (dashboard, CV screening, applicant lists on position
  pages) use `accounts.decorators.RECRUITMENT_STAFF_GROUPS` and
  `user_in_groups()`. That covers the 5 non-Candidate roles; superusers
  always pass.
- **Nav links:** the context processor `dashboard.context_processors.dashboard_access`
  hides links the user would be denied.
- **Feedback edit/delete:** `accounts.mixins.AuthorOrGroupRequiredMixin` lets
  through the author, a superuser, or members of `FEEDBACK_EDIT_OVERRIDE_GROUPS`
  (`interviews/views.py`: Leadership Manager, Senior Reviewer). It
  deliberately doesn't use `change_interviewfeedback`, because those roles
  don't hold that permission.
- **Record pages** (candidate, position, interview) check permissions per
  section in the view (`user.has_perm(...)` or `user_in_groups`). A section
  the user can't access is not rendered at all.
- **Positions list:** shows Open to everyone. The Closed tab only appears
  for users with `positions.change_position`.

**Candidate group** permissions, last verified 2026-08-20:
`candidates.view_application`, `candidates.view_candidate`,
`interviews.view_interview`, `interviews.view_interviewfeedback`,
`positions.view_position`.

(History: an earlier attempt stripped all of these and left candidates
seeing nothing. It was reverted in `71ae719`, and `view_position` was added
afterwards.)

### Known gaps (flagged, not built)

- **Feature #7: candidate self-service scoping (deferred by the user).**
  Nothing links a `User` to a `Candidate` record, so the Candidate group sees
  *every* candidate, application, interview and feedback record. A proper fix
  needs:
  - a nullable FK `Candidate.user`
  - queryset scoping in the list and detail views for the Candidate group
  - a decision on which interviews and feedback a candidate can see
- **Closed positions** are hidden from lists for non-managers but still
  reachable by direct URL. A restriction was added once and then reverted,
  because it wasn't approved. It's awaiting the user's decision.
- **Unassigned interviews:** feedback creation doesn't check that the author
  is the interview's assigned `interviewer`. That field is optional, and
  existing interviews have none.
- **Automated CV screening decision (user said: disclose now, fix later).**
  `cv_screening/views.py` `upload_application_cv` sets "CV Screening
  Passed" (score >= 0.7) or "CV Screening Failed" (< 0.4) with no human in
  between, and the status signal emails the candidate. That is a solely
  automated decision under UK GDPR Art. 22. The privacy notice, candidate
  notice and help page disclose it and offer human review. The intended fix
  is to require recruiter confirmation before a Failed outcome is emailed.
  If the thresholds change, update those pages too
  (`marketing/tests.py` checks the numbers match).
- **Public copy vs Candidate-group access.** The landing role card ("no
  access to internal feedback") and the candidate notice ("only the
  recruitment team" sees applications) describe intended behaviour. Today
  the Candidate group can view all candidates, applications, interviews and
  feedback. Feature #7 closes this.
- **Security page claims only what's verified.** No HTTPS redirect, HSTS or
  secure-cookie settings exist yet; add them at deployment and then update
  `templates/marketing/security.html`.

## Interviews domain

- **`Interview.interviewer`** is a nullable FK to `User`. Only recruitment
  staff can be picked (enforced in `InterviewForm`). The "My interviews" view
  (`interviews/mine/`) lists the interviews assigned to the current user.
- **`InterviewFeedback`** is a FK to `Interview` (not one-to-one), with:
  - `parent`: a self-FK used for threaded replies
  - `author`, `updated_at`
  - `rating` (1–5) and `recommendation`, both required only on root entries,
    enforced in `FeedbackForm.clean()`
- **Thread page:** `interviews/<pk>/feedback/` (`FeedbackThreadView`). Replies
  are at `feedback/<pk>/reply/`.
- **`FeedbackAuditLog`** has one row per EDITED (only when something actually
  changed) or DELETED action, with a JSON `diff` of old and new values.
  `feedback` is `SET_NULL` and `interview` is snapshotted, so deletions stay
  logged after the row is gone.
- **`StaffNotification`** is an in-app notification. It is created when
  someone other than the author edits or deletes their feedback. Unread
  count: `interviews.context_processors.staff_notifications`, shown on the
  bell. `StaffNotificationListView` renders before marking entries read, so
  "New" badges still show.

## Email notifications (`notification_client` + `notification-service`)

- **Signals:** `candidates/signals.py` fires on an application status change,
  and `interviews/signals.py` fires when an interview is created. Both publish
  events via `transaction.on_commit` (event types are in
  `notification_client/event_types.py`).
- **Publisher:** `publish_event()` only does `sqs:SendMessage` and never
  raises. If `NOTIFICATIONS_SQS_QUEUE_URL` is empty it does nothing.
- **Local mode:** `NOTIFICATIONS_LOCAL_MODE=True` renders the email in-process
  with the real Lambda templates and writes it to `local_notifications/`
  (gitignored). No AWS needed.
- **AWS pipeline:** SQS (+DLQ) → Lambda → SES, with a DynamoDB audit log and a
  CloudWatch/SNS alarm on the DLQ. See `notification-service/README.md`.

## UI system

Design direction and rejected alternatives are in the memory file
`project-ui-design-direction`. Summary:
- **Look:** dark-first (light via a persisted toggle, `data-theme="light"`),
  slate palette `#06141b #112120 #253745 #4a5c6a #9ba8ab #ccd0cf`, Geist and
  Geist Mono, Lucide icons.
- **Status colours:** status is monochrome plus an icon, with no extra hues.
  Badges use `data-status="{{ value }}"` matched against the exact model
  choice strings in CSS.

Files:
- **Styles:** `accounts/static/css/site.css` is the full component system
  (tokens, shell, cards, KPIs, tables, tabs, forms, badges, timeline,
  stepper, motion). `landing.css` styles the public site only.
- **Scripts:**
  - `accounts/static/js/app-shell.js`: theme toggle, sidebar collapse,
    count-up, clickable `tr[data-href]` rows, `/` to focus search, re-init
    after HTMX swaps
  - `landing-webgl.js`: the aurora shader
  - `landing-reveal.js`
- **Base template:** `templates/base.html` has the grouped sidebar with the
  user card, the topbar (search, "New" quick-create menu gated by
  permissions, theme toggle, notifications bell), and toasts.
- **Shared components:** `templates/components/` holds `head_icons`,
  `brand_mark`, `field`, `form_errors`, `pagination`, `list_toolbar`, and
  `confirm_delete` (which lists cascade counts).
- **Page layouts:**
  - Dashboard: command center.
  - Detail pages: record hubs with related data and activity.
  - List pages: data table with stage tabs showing counts, search, filters
    and sort, via `accounts/listing.py` `ListToolbarMixin`. Tab counts come
    from one `aggregate(Count(filter=Q))` query.
  - Forms: sectioned, with a context rail.
- **Template tags:** `accounts/templatetags/ui.py` has `url_replace`,
  `initials`, `percent_of`, `nonzero`, `score_pct`.
- **Logout:** `LOGOUT_REDIRECT_URL = "/"`.
- **Favicon:** the "flow mark" (two nested arcs) in `accounts/static/img/` as
  svg, png and ico. `/favicon.ico` redirects there.
- **Unused templates:** `candidates/cv_form.html` and `cv_list.html` aren't
  referenced anywhere. The user hasn't decided whether to delete them.

## Django gotchas hit in this codebase

- **Stray `order_by` in grouping queries.** Ordering fields leak into `GROUP BY`.
  Call `.order_by()` before `values().annotate()`. This caused a pipeline
  undercount bug.
- **`TemplateResponse` renders lazily.** Call `response.render()` before
  mutating data the template reads.
- **Static file storage.** WhiteNoise `CompressedStaticFilesStorage` is
  non-manifest, so `static()` at import time is safe.

## Throwaway accounts

`__*_check__` / `__*_preview__` users are created for verification and
deleted after. If one lingers in either database, it's safe to delete.

## Public site (`marketing` app)

Dark-only, uses `landing.css`; separate from the app shell in `base.html`.
- **Pages:** `/` landing, `/help/`, `/status/`, `/security/`,
  `/privacy/`, `/terms/`, `/cookies/`, `/accessibility/`,
  `/candidate-notice/`. Plus `robots.txt` (disallows every app path),
  `sitemap.xml` (public pages only), and `/.well-known/security.txt`
  (its `Expires` must be bumped before 2027-09-16).
- **User rule:** no same-page anchor links in the nav or footer; every link
  goes to a real page. The only in-page links allowed are the skip link and
  the table of contents on document pages.
- **Templates:** `templates/marketing/public_base.html` (nav: Help, Status,
  Security, Privacy + Log in / "Open Candidflow" when signed in; column
  footer with version and live status dot), `doc_base.html` (hero, sticky
  table of contents, prose, contact card). `templates/404.html` and
  `500.html` extend the public base; 500 renders with no context.
- **Copy framing:** operator is "Candidflow" under UK GDPR, England and
  Wales law, AWS Singapore region, 12-month retention after the final
  decision. Contact addresses are `@candidflow.example` placeholders set in
  one place: `CONTACTS` in `marketing/views.py`. `LEGAL_UPDATED` there is
  the "Last updated" date. Every claim must match the code; check before
  editing.
- **Status:** `marketing/status.py` runs real checks (web, DB `SELECT 1`,
  CV storage and notifications as config-only checks, labelled as such). No
  hostnames or bucket names are shown. The footer summary is cached for 60s.
  `/healthz/` is unchanged for uptime monitors.
- **Version:** `settings.CANDIDFLOW_VERSION` (env `CANDIDFLOW_VERSION`,
  default 1.0.0).
- **Crawling:** `base.html` and `login.html` carry
  `<meta name="robots" content="noindex, nofollow">`.
- **Deferred by the user:** a password reset flow (the Help page tells people
  to contact an administrator). They'll build it once per-user accounts exist
  after deployment.
- **Not done yet, landing only this round:** the login page doesn't link to
  the terms or privacy notice, even though the terms say signing in means
  agreeing to them.
