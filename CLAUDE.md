# Candidflow (recruitment tracker) — session notes

Internal Django 5.0 recruitment tracker, branded **Candidflow**. Server-rendered
class-based views + ModelForms + templates, HTMX on the dashboard only. No
DRF/API layer.

Eight roles via Django Groups: Recruiter, HR Interviewer, Technical
Interviewer, Senior Reviewer, Leadership Manager, Department Chief,
Administrator, Candidate. Roles are shared; accounts never are. Every staff
member has their own login, and `accounts.decorators.RECRUITMENT_STAFF_GROUPS`
is what "is this a staff account?" means everywhere in the app.

Apps:
- `accounts`: login/logout, profile, global search, shared mixins, the list toolbar, `ui` template tags
- `candidates`: candidates and applications
- `positions`
- `cv_screening`: CV upload, match scoring, results
- `interviews`: interviews, threaded feedback, audit log, staff notifications
- `dashboard`: see `dashboard/CLAUDE.md`
- `marketing`: the public site (see Public site below)
- `portal`: the candidate portal (see Candidate portal below)

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
- Current suite: **362 tests, all passing** (2026-09-20).
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
- **Positions:** the list shows Open to everyone, and the Closed tab only
  appears for users with `positions.change_position`. `PositionDetailView`
  filters to `is_open=True` for everyone else, so a closed role 404s by
  direct URL too.

**Candidate group holds no permissions** (cleared in the real database on
2026-09-18, with the user's approval). Those model-wide `view_*` grants let a
candidate account read every candidate, application and interview, not just
their own. The portal scopes by the record linked to the login instead, so it
needs none. `assign_role_permissions` now clears the group rather than
granting them — don't add any back.

(History: an early attempt to strip them predated the portal and left
candidates unable to see anything at all. It was reverted in `71ae719`. This
time the portal replaces what they lost.)

### Known gaps (flagged, not built)

- **Feedback isn't restricted to the assigned interviewer**, and that is
  deliberate (user's decision, 2026-09-18): rounds get covered at short
  notice, and every entry records its author anyway.
- **Interviews aren't department-scoped outside the dashboard**, and that is
  deliberate too (user's decision, 2026-09-20). `InterviewListView` and
  `InterviewDetailView` gate on `interviews.view_interview` only, so a
  Technical Interviewer scoped to one department on the dashboard can still
  open any interview by URL. Same reasoning as feedback. Don't "fix" it.
- **Any staff account can open any CV**, for the same reason — recruiters
  and reviewers work across departments. Accountability is the audit record
  (`CV_DOWNLOADED`), not a restriction.
- **Security page claims only what's verified.** It now describes the real
  transport security (HTTPS at the CDN, the origin refusing anything else,
  HSTS, secure cookies). If the CloudFront layer is ever removed, that copy
  becomes false and has to change with it.

Closed since: candidate self-service scoping (the portal), and the
automatic CV pass/fail decision (a recruiter now confirms outcomes).

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
- **Deployed 2026-09-20** as CloudFormation stack
  `recruitment-tracker-notifications` in `ap-southeast-1`. The queue URL is
  set on the environment, and the stack's least-privilege
  `RecruitmentTrackerNotificationPublish` policy is attached to
  `aws-elasticbeanstalk-ec2-role`, so the app can publish and do nothing
  else.
- **Sender is `ansy.pppm@gmail.com`**, an SES *email* identity — no domain
  is involved, which is what makes this work without one. SES is in
  **sandbox**: it will only send to addresses that are themselves verified.
  Verifying an address covers both directions, so the sender is also a valid
  recipient.
- **Two confirmations are needed once, by clicking a link:** the SES sender
  verification, and the SNS subscription for the DLQ alarm. Until the first
  is done, every send fails. Check with
  `aws ses get-identity-verification-attributes --identities <address>`.
- **Verified end to end 2026-09-20**, twice: once publishing from a
  developer machine, and once by submitting the live password-reset form,
  which is the path that matters — it proves the *instance role* can publish.
  Both landed `SENT` in the audit table with an SES message id, and the
  dead-letter queue stayed empty.
- **Deliverability caveat:** sending as a `gmail.com` address fails SPF,
  because Google's records don't authorise Amazon's servers. Mail usually
  still arrives but often in spam. A domain is the only real fix.

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

## Django gotchas hit in this codebase

- **Stray `order_by` in grouping queries.** Ordering fields leak into `GROUP BY`.
  Call `.order_by()` before `values().annotate()`. This caused a pipeline
  undercount bug.
- **`TemplateResponse` renders lazily.** Call `response.render()` before
  mutating data the template reads.
- **Static file storage.** WhiteNoise `CompressedStaticFilesStorage` is
  non-manifest, so `static()` at import time is safe.

## Test and demo data in the real database

- **`candidate01`** is linked to a candidate record named **"Test Candidate
  (QA)"** (`test.candidate01@candidflow.example`, a reserved domain that can
  never receive mail). It is a permanent candidate-side test login, and it is
  meant to be obvious in the candidate list that it isn't a real applicant.
- **Real candidates create their own records** by applying; those are marked
  `source="public"`. Anything staff-entered is `source="staff"`.
- **`seed_demo` data is separate again**: `demo.` usernames and
  `@demo.candidflow.example` addresses, removed with `--clear --yes`.

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

## Candidate portal (`portal` app)

Candidates get their own login and their own area at `/portal/`. Staff pages
and candidate pages never mix.

- **The link:** `Candidate.user` is a nullable `OneToOneField` to `User`
  (`SET_NULL`). It is the only connection between a login and a candidate
  record. Never match candidates to users by email address.
- **Scoping:** `portal/mixins.py` `CandidateRequiredMixin` is the single
  boundary. Every portal view starts from `self.candidate`, and no portal URL
  takes a candidate id, so one candidate cannot address another's data.
  A user with no linked candidate, or one in a staff group, gets 403.
- **Defence in depth:** `portal.middleware.CandidatePortalMiddleware`
  redirects candidate-linked accounts away from staff paths, so a permission
  granted by mistake in the database doesn't open the staff app to them.
- **What candidates never see** (decided by the user): interview feedback,
  CV match scores, interviewer names, and any sign of other applicants. The
  way to keep that true is to not put it in the context.
- **Two ways in.** Applying through the public careers pages creates a
  candidate account once the email is confirmed (see Public applications).
  A recruiter can also invite an existing candidate record directly.
- **Recruiter invites:** a recruiter with `candidates.change_candidate`
  posts to `candidate-invite`; `CandidateInvite.issue()` revokes any
  outstanding invite and creates a new token valid for 7 days
  (`INVITE_VALID_DAYS`). Accepting sets a password, creates the user with the
  email as username, adds them to the Candidate group and links the record.
  Expired, revoked, used and unknown tokens all render the same 404, so the
  token can't be used to probe whether a candidate exists.
- **Candidates can:** see their applications and stage timeline, see their
  interviews (type, time, status), upload or replace a CV while the status is
  `Applied` or `CV Screening`, and withdraw an application. Withdrawal sets
  the new `Withdrawn` status, cancels scheduled interviews, and notifies
  recruiters plus the assigned interviewers.
- **Deleting a candidate** deactivates the linked login, because `SET_NULL`
  would otherwise leave an account that can still sign in.
- **An invite for an email that already has a login is refused with 409**
  (`email_is_available()` in `AcceptInviteView`), rendering the same
  "link no longer works" page with `email_taken`. Correct — it prevents a
  candidate login colliding with a staff one — but it means an applicant
  whose address matches an existing account cannot self-register, and that
  is a support case, not a bug to fix.
- **Login fork:** `LOGIN_REDIRECT_URL` points at
  `accounts.views.PostLoginRedirectView`, which sends candidates to the
  portal, staff to the dashboard, and anyone else to their profile.
- **Password reset** exists for everyone now. The email is published to the
  notification pipeline by `accounts/password_reset.py`, so Django's
  `EMAIL_BACKEND` is still unused.
- **The Candidate group has no permissions**, and must not be given any.
  See Access control above.

## Screening outcomes are a human decision

Uploading a CV scores it and moves the application to `CV Screening`. It
never writes `CV Screening Passed`/`Failed`. Only
`cv_screening.views.confirm_screening_outcome` does, and it needs staff group
membership plus `candidates.change_application`. The public copy says a
person decides, and `marketing/tests.py` fails if automation is wired back in
without the copy being corrected.

## Public applications (careers pages)

Anyone can browse open roles and apply without an account. `marketing/careers.py`
holds the views, `candidates/applications.py` the logic that matters.

- **Pages:** `/careers/`, `/careers/<pk>/`, `/careers/<pk>/apply/`, and the
  emailed link at `/apply/confirm/<token>/`. Only `is_open=True` positions are
  listed or accept applications.
- **Nothing enters the pipeline unconfirmed.** A submission creates a
  `PendingApplication` and nothing else. Recruiters never see these rows. The
  emailed link is what creates the Candidate, Application and CV. This is what
  stops anyone putting a fake application under someone else's name.
- **Linking to an existing candidate happens only at confirmation**, matching
  on email, because clicking the link proves the address is theirs. Never link
  on email anywhere earlier.
- **Duplicates** are detected at confirmation, not submission: one live
  application per role (`CLOSED_STATUSES` don't block re-applying). Telling
  someone at submission time that they'd already applied would leak who is in
  the pipeline.
- **The form never reveals whether an address is known.** Every path renders
  the same "check your email" page. Keep it that way.
- **Rate limits** (`candidates/applications.py`): 3 per email and 8 per IP per
  hour, counted in the database so they survive restarts and hold across
  instances. The IP is erased as soon as the application is confirmed.
- **Required:** name, email, CV (PDF/DOCX, 5 MB, shared rules in
  `cv_screening/uploads.py`) and ticking the terms box, which records
  `Candidate.terms_accepted_at`. Phone and message are optional; the message
  is copied to `Application.applicant_message` and shown to recruiters.
- **`Candidate.source`** is `staff` or `public`, shown on the candidate record.
- **Housekeeping:** `candidates.applications.purge_expired_pending()` deletes
  unconfirmed submissions and their CVs, via `manage.py
  purge_pending_applications` on a weekly timer. See The scheduled
  housekeeping below.

## Two sign-in doors

One accounts system, two pages (`accounts/login_forms.py`):
- `/accounts/login/` — staff, with organisation-issued credentials. Refuses
  candidate accounts.
- `/portal/login/` — candidates, using the email they applied with. Refuses
  staff accounts and accounts with no linked candidate.

Both checks run after the password is verified, so neither page says anything
about accounts that don't exist. The public site's "Sign in" button points at
the candidate door; staff sign-in is linked in the footer.

## Demo data (`manage.py seed_demo`)

One worked example of the whole pipeline, for trying things out and for
showing the app to someone:

```
python manage.py seed_demo --with-permissions   # local SQLite
python manage.py seed_demo --clear              # remove it again
```

- **Creates:** an open Backend Engineer role with a screening profile, one
  candidate (Maya Reyes) with a real .docx CV that is scored through the
  normal code path, an application at "Technical Interview", a completed HR
  round with feedback and a reply, an upcoming technical round, four extra
  applications so the pipeline chart isn't empty, an unconfirmed public
  application, and a portal invite. It prints every login and link at the end.
- **The CV deliberately misses one required skill**, so the score lands mid-
  range and "missing required" isn't empty — the case a recruiter has to
  think about.
- **Everything it creates is tagged** (`demo.` usernames, `@demo.candidflow.example`
  emails, `[demo]` in the position description and profile name), and each run
  clears the previous demo first. It never touches other records.
- **Guards:** refuses to run against anything but local SQLite unless `--yes`.
  Group permissions are only touched with `--with-permissions`, which applies
  the same matrix as `assign_role_permissions` except that the Candidate group
  is left empty (the portal needs no model permissions).
- **The password is generated per run and printed**, never stored in the repo.
  Set `CANDIDFLOW_DEMO_PASSWORD` to pick your own. Clear the demo afterwards
  with `--clear --yes`; don't leave it in a real database.

## Secrets

- **`.env` is gitignored and has never been committed.** `.env.example` holds
  the empty template.
- **No password is hardcoded anywhere in the repo.** `seed_demo` generates one
  per run and prints it; set `CANDIDFLOW_DEMO_PASSWORD` to choose your own.
  A test fails if a literal password reappears in that command.
- **Leak, handled 2026-09-18:** the live RDS password, username and hostname
  were hardcoded in `config/settings.py` in commit `c65b19b`. History was
  rewritten with `git filter-repo` and all four branches force-pushed, so the
  values are gone from every reachable commit. **GitHub still serves the old
  commits by their original SHA** (verified), and will until Support purges
  them, so the credential is compromised until it is rotated. Rotation is not
  optional.
- **`SECRET_KEY`** falls back to a development placeholder when the
  environment variable is missing. That fallback must never be used in a
  deployed environment.

## Signing up (candidates)

There is no separate sign-up form, on purpose: an account exists to follow an
application, so applying is what creates one.

- `/signup/` (`marketing/careers.py` `SignupView`) explains the three steps,
  lists up to five open roles and links straight into the apply form. It has
  no form of its own — a test asserts that, since a second, unverified way to
  create an account would undo the confirmation step.
- Linked from the public nav ("Create account"), the footer, the careers page
  and the candidate sign-in page.
- **The candidate sign-in username field is `type="text"`**, not `"email"`.
  Accounts created before the portal have plain usernames and the browser
  would refuse to submit them. The server never required an email.

## Housekeeping commands

- `manage.py purge_pending_applications [--days N] [--dry-run]` deletes
  unconfirmed public applications and their CVs once their link expired more
  than `PENDING_RETENTION_DAYS` (30) ago. It runs weekly from the instance
  crontab, because the privacy notice promises that deletion. Confirmed
  applications are candidate records by then and are never touched.
- `manage.py check_notifications [--send EMAIL]` reports whether email is
  live, in local mode, or off, and can put one test message through the
  configured path. With email off, nobody can confirm an application, accept
  an invite or reset a password.

## Production configuration

Everything below is off under `DEBUG` and under the test runner (`RUNNING_TESTS`
in settings), so local work and tests are unaffected.

- **HTTPS:** `SECURE_SSL_REDIRECT`, HSTS (1 hour to start, raise via
  `DJANGO_HSTS_SECONDS`), secure + HttpOnly cookies, nosniff, same-origin
  referrer policy.
- **How the origin learns the request was encrypted.** Not
  `X-Forwarded-Proto`: CloudFront manages that header itself, and an origin
  custom header of that name never reaches the origin. Setting it produced a
  redirect loop in production — Django saw a plain request, redirected to
  HTTPS, and arrived back at itself. `SECURE_PROXY_SSL_HEADER` therefore
  reads `X-Origin-Verify` and matches `CLOUDFRONT_ORIGIN_SECRET`, which
  carries the same fact: CloudFront only forwards after redirecting the
  viewer to HTTPS. It is also the stronger signal, since `X-Forwarded-Proto`
  can be forged by anyone who reaches the origin and the secret cannot.
  Without the secret set — local work, tests, a direct origin — the
  conventional header applies unchanged.
- **`/healthz/` is answered by middleware**, not a view.
  `config.middleware.HealthCheckMiddleware` runs first and returns before
  `request.get_host()` is ever called. A load balancer checks its targets by
  address, so Host is the instance's private IP — never in `ALLOWED_HOSTS`,
  and unknowable in advance — and Django would answer 400, the target would
  read as unhealthy, and the environment would cycle instances while every
  setting looked correct. Running first also keeps the HTTPS redirect off it;
  `SECURE_REDIRECT_EXEMPT` stays as a second line of defence. The path
  deliberately has no URL route.
- **Startup guards:** with `DEBUG` off, a missing `SECRET_KEY` or empty
  `DJANGO_ALLOWED_HOSTS` raises rather than starting.
- **Static files** use hashed names (manifest storage) only in deploys, so
  `collectstatic` must run first. **A configuration change wipes them.** It
  re-extracts the source but doesn't run the `.ebextensions` container
  commands, and `staticfiles/` is generated rather than committed — so it
  disappears, every `{% static %}` lookup raises, and the whole site returns
  500. That happened live on 2026-09-20 when `CLOUDFRONT_ORIGIN_SECRET` was
  added. `.platform/confighooks/predeploy/01_collectstatic.sh` now
  regenerates them on a config change; it exits 0 whatever happens, because
  blocking every future config update would be worse than the 500 it
  prevents. A redeploy also fixes it. The favicon URL is resolved per request
  rather than at import time, for the same manifest reason.
- **Cache:** `DatabaseCache` in `candidflow_cache`. Run
  `manage.py createcachetable` in every environment. Throttling fails open if
  it's missing, so a forgotten table degrades protection rather than locking
  everyone out.
- **Admin path** is `DJANGO_ADMIN_PATH` (default `admin`).
- **Logging** goes to stdout at INFO.

**Variable names are `DJANGO_`-prefixed** (`DJANGO_DEBUG`,
`DJANGO_ALLOWED_HOSTS`), and `.env.example` is the only record of what a
deployment must set. A `.env` carrying the older bare `DEBUG`/`ALLOWED_HOSTS`
names silently leaves both unset, which trips the startup guard and the app
does not boot at all. `config/test_deployment.py` now fails if `.env.example`
defines a key twice (dotenv keeps the last one, so an empty duplicate wins)
or if `settings.py` reads a variable the template never mentions.

### Deployment shape

**The environment already exists** and predates this work: application
`recruitment-tracker`, environment `recruitment-tracker-env` (`e-entm4uhcbt`),
CNAME `recruitment-tracker-env.eba-prejxa8h.ap-southeast-1.elasticbeanstalk.com`,
created by `eb create` on 2026-07-30. Do not create a second application;
deploy to this one.

**The live site is `https://dmy7zm623g8ab.cloudfront.net`** (distribution
`E93RL72H4YX1I`). The Elastic Beanstalk hostname answers 403 to everything
except `/healthz/`, which is the origin lock working — reaching the site any
other way is not possible, by design.

**Current code was deployed 2026-09-20** and the environment is Green. Before
that it ran commit `e685185` from 4 August, 30 commits behind, with "No Data"
health since 17 August.

**That health outage and the first failed deploy had one cause, worth
remembering.** Someone had attached a custom instance profile
(`recruitment-tracker-eb-s3-role-v2.`, holding only `AmazonS3FullAccess`)
directly to the EC2 instance, bypassing Elastic Beanstalk. EB's own
`IamInstanceProfile` setting still read `aws-elasticbeanstalk-ec2-role`, so
the console showed the right answer while the instance used something else.
Without `AWSElasticBeanstalkWebTier` the instance could not report health or
create log streams. Fixed with `aws ec2
replace-iam-instance-profile-association`. **If health ever goes quiet again,
compare the instance's actual profile against the environment's setting
before anything else** — they are allowed to disagree, and nothing warns you.

**`DATABASE_URL` had never been set on it**, and all five `DB_*` values were
therefore read by nothing — `settings.py` selects Postgres on the *presence*
of `DATABASE_URL` alone. Production had been running on SQLite on the
instance, wiped by every deploy, while RDS held the real data. Set 2026-09-20;
the deploy log's `No migrations to apply` is what proves the connection is
real, since a fresh SQLite would have applied all thirty.

One Elastic Beanstalk **single-instance** environment (`t3.micro`, **Python
3.13** on AL2023, `ap-southeast-1`) with **CloudFront in front**. Python 3.12
was the earlier recommendation, on the assumption of a fresh environment; you
cannot change platform branch in place, and local development is 3.13 with
the full suite passing, so matching it beats Django 5.0's official support
matrix here. No domain:
AWS will not issue a certificate for `*.elasticbeanstalk.com`, so CloudFront
supplies both the hostname and a free managed certificate. Cost target is
zero, which is why there is no load balancer — an ALB alone costs more than
everything else combined.

- **`.ebextensions/instance.config`** pins the environment type, instance
  type, 7-day CloudWatch log retention, and a 1 GB swap file (1 GB of RAM
  isn't enough for `pip install` of this requirement set; the deploy dies
  with a bare "Killed").
- **`ALLOWED_HOSTS` is wildcarded** (`.cloudfront.net`,
  `.ap-southeast-1.elasticbeanstalk.com`) because the real hostnames don't
  exist until AWS creates them. Both are needed: CloudFront forwards the
  viewer's Host for pages, and sends the origin's own hostname for
  `/static/*`, which has no origin request policy.
- **`config.middleware.CloudFrontOriginMiddleware`** refuses any request
  that didn't come through CloudFront, matching `CLOUDFRONT_ORIGIN_SECRET`
  against the `X-Origin-Verify` origin custom header with
  `compare_digest`. Without it the elasticbeanstalk.com hostname would serve
  the whole site over plain HTTP and the certificate would be decorative.
  Empty secret means the check is off, which is what local work and tests
  want. `/healthz/` never reaches it — `HealthCheckMiddleware` runs first —
  and a test asserts that, because otherwise every deploy would roll back.
- **CloudFront caching is disabled** on the default behaviour: every page is
  session-specific. `/static/*` is cached, which is safe only because
  manifest storage content-hashes every filename.
- **A WAF is attached and cannot be removed.** The CloudFront console's
  "single website" wizard silently creates a WebACL
  (`CreatedByCloudFront-*`), and because the distribution is on a pricing
  plan, `UpdateDistribution` refuses to clear `WebACLId`: *"Distributions
  with a pricing plan subscription must have a web ACL resource."* Removing
  it means cancelling the plan first, in the console.
- **That WAF blocked every CV upload**, and the symptom is misleading: a
  CloudFront 403 page reading "Request blocked", with `Server: CloudFront`
  and `X-Cache: Error from cloudfront` — never reaching Django, so nothing
  appears in the application logs. The cause is `SizeRestrictions_BODY` in
  `AWSManagedRulesCommonRuleSet`, which blocks request bodies over **8 KB**
  while the app allows 5 MB. Fixed 2026-09-20 by overriding that one rule to
  `Count`. Rule changes take a minute or two to reach the edge, so retest
  rather than concluding the fix failed.
- **If uploads break again, check WAF before the application.** A `.docx` is
  a ZIP, and binary bodies can trip other body-inspection rules
  (`CrossSiteScripting_BODY` and friends) the same way. `aws wafv2
  get-sampled-requests` names the matching rule.
- **`.gitattributes` forces LF** on `*.sh`, `.ebextensions/*.config` and
  `.platform/**`. `core.autocrlf` is true on the development machine, and a
  shell script checked out with CRLF fails on Amazon Linux with "bad
  interpreter" — a failure that surfaces during a deploy, far from its cause.
- **Deploying:** the EB CLI is not in the project venv (its pins conflict).
  It lives in an isolated venv; `eb init` has been run and
  `.elasticbeanstalk/config.yml` maps the `ui-redesign` branch to the
  environment. `eb deploy` bundles from git HEAD, so `.env`, `db.sqlite3`,
  `venv/` and `staticfiles/` are all excluded — verified.

Required environment variables in production: `SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` (with scheme),
`DATABASE_URL` + `DB_*`, `NOTIFICATIONS_SQS_QUEUE_URL`, `DJANGO_ADMIN_PATH`
and the `CANDIDFLOW_*_EMAIL` contacts. All of them are listed with notes in
`.env.example`.

Decisions taken 2026-09-18: HSTS covers the main domain only (subdomains off
until every one is known to be HTTPS); the admin moves off `/admin/` via
`DJANGO_ADMIN_PATH`; contact addresses are three separate aliases
(help/privacy/security) on a real domain, still to be supplied.

## Authentication protections

- **Sign-in throttling** (`accounts/throttling.py`): 6 failures per username
  and 20 per IP in 15 minutes; checked *before* the password, so a lockout
  can't be brute-forced past, and cleared on success.
- **Password reset** is capped at 5 per IP per hour and always renders the
  same confirmation page, so neither form reveals who has an account.

## Uploads

- **All three upload paths call `validate_cv_file()`** — the candidate
  portal, the public application form, and the staff "Screen CV" button.
  The staff one didn't until 2026-09-20: it went straight from
  `request.FILES` to storage with no size cap, no extension check and no
  signature check, which is the whole thing `cv_screening/uploads.py` exists
  to prevent. If a fourth upload path is ever added, it calls this too.
- Validated by **file signature** as well as extension: a `.pdf` that isn't
  a PDF is refused.
- `score_cv_safely()` is the only way CVs get scored. A malformed PDF used to
  return a 500 on all three upload paths; now the file is kept, the failure is
  logged, and the person is told it couldn't be read.

## Audit log

`accounts/audit.py` + `AuditEvent`. One append-only table for the whole app;
`FeedbackAuditLog` stays as it is for feedback before/after values.

- **Write with** `audit.record(action, actor=..., request=..., target=..., **detail)`.
  It never raises: a failed audit write must not roll back the action.
- **Sign-in, sign-out and failed sign-in** come from Django's auth signals
  (`accounts/signals.py`), so they record however the sign-in happened.
- **Immutable:** `save()` refuses to rewrite an existing row.
- **Labels are snapshots**, so entries survive the actor or target being
  deleted.
- **Opening a CV is recorded** (`CV_DOWNLOADED`, from
  `cv_screening.views.view_cv`). It's the most sensitive data here and was
  the one way to read it that left no trace. `CV_UPLOADED` is defined but
  not yet written anywhere.
- **IP and user agent are kept for authentication events only** — personal
  data, and only useful there.
- **Readable by** Leadership Manager, Administrator and superusers.
- **Retention:** 730 days, applied by `manage.py purge_audit_events`.

## Staff accounts

`accounts/staff.py` (rules) and `accounts/staff_views.py` (screens). Kept out
of the Django admin deliberately: these actions must follow the rules and be
audited, and the admin would let a superuser bypass both.

- **Administrators create accounts**; the work email is the username. The
  account starts with **no usable password** — the person sets their own from
  an emailed link (`StaffInvite`, 7 days, one use). An administrator never
  knows a colleague's password.
- **`must_change_password`** is enforced by middleware, not per view.
- **Deactivate, never delete:** `is_active=False` plus session revocation.
  Django's ModelBackend re-checks `is_active` per request, so open sessions
  stop working immediately. Feedback and audit history survive, and nobody
  else with the same role is affected.
- **The last administrator** cannot be demoted or deactivated.
- **Sessions:** staff get 8 hours of *idle* time
  (`SESSION_SAVE_EVERY_REQUEST` makes it rolling); candidates keep two weeks.
  "Sign out everywhere" is `revoke-my-sessions`.
- **`ASSIGNABLE_ROLES`** is de-duplicated: Department Chief and Administrator
  are in `RECRUITMENT_STAFF_GROUPS` too.

## Departments and chiefs

`Department.chiefs` (M2M) records who chairs a department; the **Department
Chief** group carries the permissions. Several chiefs per department is
deliberate. Naming a chief also grants the role. Chiefs are department-scoped
on the dashboard, like technical interviewers.

## Interview ownership and delegation

Three separate concepts, never collapsed into one field:

- **`Interview.created_by`** — who scheduled it.
- **`Interview.assigned_interviewer`** — who owns it (renamed from
  `interviewer`; the column was renamed, not recreated).
- **`InterviewDelegation`** — who it's been offered to, by whom, why, and
  what they said. Its own table so history survives reassignment.
- **`Interview.conducting_interviewer`** is the single answer to "who is
  turning up": the delegate only once they have **accepted**.

Rules (all decided with the user, all tested in `interviews/test_delegation.py`):

- Only the assigned interviewer, a chief of that department, or an
  administrator may delegate; only the person asked may answer. Enforced on
  GET and POST.
- **One hop.** A delegate cannot delegate onward.
- Declining needs a reason and returns the round. A new offer supersedes the
  outstanding one.
- Cross-department delegation is **allowed and flagged**, not blocked.
- Pending offers expire 48 hours before the interview
  (`manage.py expire_delegations`); cancelling or completing closes them.
- Candidates see none of it — not the delegation, not the reason, not any
  interviewer's name.

Interviews also carry `location` and `meeting_link`, which candidates see.

## The scheduled housekeeping

Three commands do work nothing else does, so they run on a timer:

- `expire_delegations` — hourly. Pending offers within 48 hours of the
  interview revert to the assigned interviewer. The only one with a same-day
  effect: without it an interview arrives with nobody expecting to run it.
- `purge_pending_applications` — Sundays. Unconfirmed public applications and
  their CVs after 30 days, which is what the privacy notice promises.
- `purge_audit_events` — Sundays. Audit entries past 730 days.

**`cron.yaml` is the wrong tool here.** Elastic Beanstalk periodic tasks only
exist on a *worker* environment, and there the daemon POSTs to a URL rather
than running a command. This is a web tier (`WSGIPath` in
`.ebextensions/django.config`), so a `cron.yaml` would do nothing, silently.

`.ebextensions/cron.config` installs a real crontab instead, and
`scripts/housekeeping/` holds one script per command over a shared `_lib.sh`.
The parts worth knowing:

- **cron has none of the environment properties.** The deploy copies
  `/opt/elasticbeanstalk/deployment/env` (which only exists during a deploy)
  to `candidflow_env`, root-only because it holds the database password.
  Without it a job would run on the development `SECRET_KEY` and no
  `DATABASE_URL`.
- **The executable bit** is set at deploy time (`chmod +x`), because git on
  Windows doesn't carry it.
- **Output** goes to `/var/log/candidflow-housekeeping.log`, one start line
  and one exit status per run, rotated weekly.
- **`config/test_deployment.py`** asserts the schedule and the scripts still
  name real management commands, so a rename can't quietly stop the
  deletions.
- **Known limit:** the crontab lands on every instance. Correct for one; on
  two or more, all of them fire. The purges are safe (re-deleting does
  nothing), but `expire_delegations` could notify twice. Move to EventBridge
  Scheduler before scaling out.
