# Candidflow — Engineering Record

**Last updated:** 2026-09-20
**Status:** deployed, HTTPS layer in progress
**Repository branch:** `ui-redesign`

---

## 1. Purpose of this document

`CLAUDE.md` is the project's *reference* document: it describes how the system
works today. This document is the *record*: what was built, in what order,
which problems were found, what caused them, and which decisions were taken
deliberately rather than by default.

It exists so that the reasoning survives the work. A reader who inherits this
codebase should be able to tell the difference between something that is
missing and something that was decided against — and should not have to
rediscover a fault that has already been diagnosed once.

No credentials, secrets, hostnames or keys appear in this document.

---

## 2. What Candidflow is

An internal recruitment tracker built on Django 5.0, covering the pipeline
from a public job advert through to an interview decision.

It is server-rendered throughout: class-based views, `ModelForm`s and Django
templates, with HTMX used only on the dashboard. There is no REST API and no
front-end framework. That was a deliberate constraint — a single rendering
model is easier to secure and to reason about than two.

**Actors.** Eight roles, implemented as Django Groups:

| Role | Purpose |
|---|---|
| Recruiter | Owns candidates and applications |
| HR Interviewer | Conducts and records HR rounds |
| Technical Interviewer | Conducts and records technical rounds |
| Senior Reviewer | Reviews and can override feedback |
| Leadership Manager | Oversight, reads the audit log |
| Department Chief | Chairs a department, may delegate its interviews |
| Administrator | Manages staff accounts and roles |
| Candidate | Sees only their own applications, via the portal |

Roles are shared; **accounts never are**. Every staff member has their own
login, so every action in the audit log names a person rather than a shared
credential.

**Applications.**

| App | Responsibility |
|---|---|
| `accounts` | Authentication, profiles, search, audit log, staff administration |
| `candidates` | Candidates, applications, public application intake |
| `positions` | Open and closed roles |
| `cv_screening` | CV upload, keyword match scoring, screening outcomes |
| `interviews` | Interviews, threaded feedback, delegation, notifications |
| `dashboard` | Role-scoped overview |
| `marketing` | The public website and careers pages |
| `portal` | The candidate self-service area |

Outside Django: `notification_client/` publishes email events to a queue, and
`notification-service/` is a separate AWS SAM application that consumes them.

---

## 3. Architecture decisions

These are the choices that shaped everything else.

### 3.1 Two sign-in doors, one account system

Staff sign in at `/accounts/login/`; candidates at `/portal/login/`. Both
authenticate against the same user table, but each refuses the other's
account type — and both checks run **after** the password is verified, so
neither page reveals whether an account exists.

The alternative, one shared login page, was rejected: a candidate arriving at
a page headed "organisation credentials" is a support ticket, and a single
page makes it harder to apply different session lengths and different
redirect destinations.

### 3.2 The portal takes no identifiers from the URL

`portal/mixins.py` `CandidateRequiredMixin` is the single boundary for
candidate access. Every portal view begins from `self.candidate`, derived
from the signed-in user, and **no portal URL accepts a candidate id**.

This is the strongest available guarantee against horizontal privilege
escalation: there is no identifier to tamper with. It is enforced structurally
rather than by a check that a future view might forget.

`portal.middleware.CandidatePortalMiddleware` adds defence in depth by
redirecting candidate-linked accounts away from staff paths, so a permission
granted by mistake in the database does not open the staff application.

### 3.3 The Candidate group holds no permissions at all

Candidate accounts originally held model-wide `view_*` permissions, which
allowed any candidate account to read *every* candidate, application and
interview — not merely their own. Those permissions were removed.

The portal replaces them by scoping to the record linked to the login, so no
model permission is required. An earlier attempt to strip them predated the
portal and left candidates unable to see anything; that attempt was reverted
(`d9abb1c`). The second attempt succeeded because the replacement existed
first.

### 3.4 Nothing enters the pipeline unconfirmed

A public application creates a `PendingApplication` and nothing else.
Recruiters never see those rows. The emailed confirmation link is what creates
the Candidate, Application and CV.

This is what prevents anyone lodging a fabricated application under another
person's name. Two consequences follow deliberately:

- **Linking to an existing candidate happens only at confirmation**, matching
  on email — because clicking the link proves the address belongs to the
  person. Email is never used to link records at any earlier point.
- **Duplicates are detected at confirmation, not at submission.** Telling
  someone at submission time that they had already applied would leak who is
  in the pipeline.

Every submission path renders the same "check your email" page, so the form
cannot be used to test whether an address is known.

### 3.5 Screening outcomes are a human decision

Uploading a CV scores it and moves the application to `CV Screening`. It never
writes `CV Screening Passed` or `Failed`. Only an explicit recruiter action
does that.

The earlier behaviour set the outcome from the score automatically and emailed
the candidate a decision no person had reviewed — a solely automated decision
under UK GDPR Article 22. A test in `marketing/tests.py` fails if automation
is reintroduced without the public copy being corrected with it, so the claim
and the code cannot drift apart silently.

### 3.6 Interview ownership is three concepts, not one field

| Field | Meaning |
|---|---|
| `Interview.created_by` | Who scheduled it |
| `Interview.assigned_interviewer` | Who owns it |
| `InterviewDelegation` | Who it was offered to, by whom, why, and their answer |
| `Interview.conducting_interviewer` | Who is actually turning up |

The last is derived: the delegate only once they have **accepted**. Collapsing
these into a single "interviewer" field makes "who is running this round
tomorrow" unanswerable the moment anyone covers for anyone else.

Delegation rules, all tested in `interviews/test_delegation.py`:

- Only the assigned interviewer, a chief of that department, or an
  administrator may delegate. Only the person asked may answer. Enforced on
  both GET and POST.
- **One hop.** A delegate cannot pass it on again, because a chain makes
  ownership untraceable.
- Declining requires a reason and returns the round to its owner.
- Cross-department delegation is **allowed and flagged**, not blocked.
- Pending offers expire 48 hours before the interview and revert.
- Candidates see none of it — not the delegation, not the reason, not any
  interviewer's name.

### 3.7 The audit log is append-only

`accounts/audit.py` plus the `AuditEvent` model. One table for the whole
application.

- `AuditEvent.save()` **refuses to modify an existing row**. A log an
  administrator can quietly edit proves nothing.
- `audit.record()` **never raises**. A failed audit write must not roll back
  the action it was describing.
- Labels are **snapshots**, so an entry still reads sensibly after the actor
  or the record it refers to has been deleted.
- IP address and user agent are retained for **authentication events only** —
  they are personal data and are useful nowhere else.
- Retention is 730 days, longer than the 12 months candidate records are kept,
  so "who deleted this" remains answerable after the record is gone.

---

## 4. Chronology of work

Grouped by theme. Commit references are on branch `ui-redesign`.

### 4.1 Public website and UI (`c071311`, `63e7da1`)

A complete public site was added as the `marketing` app: landing page, help,
status, security, privacy, terms, cookies, accessibility and a candidate
privacy notice, plus `robots.txt`, `sitemap.xml` and an RFC 9116
`/.well-known/security.txt`.

Two rules were set and held:

- **No same-page anchor links** in navigation or footers. Every link goes to a
  real page. The only in-page links permitted are the skip link and the table
  of contents on document pages.
- **Every claim on the public site must match the code.** The status page runs
  real checks rather than displaying a hard-coded "operational".

The application UI was rebuilt around a dark-first design system with a
persisted light toggle, a single stylesheet of components, and status
represented monochromatically with icons rather than by colour alone.

### 4.2 Candidate portal and public applications (`63e7da1`)

Candidates received their own login and their own area. `Candidate.user` is a
nullable one-to-one link to a Django user and is the **only** connection
between a login and a candidate record.

What candidates never see, by decision: interview feedback, CV match scores,
interviewer names, and any sign of other applicants. The way that is kept true
is by not placing it in the template context at all.

Rate limits on public applications are counted in the database rather than in
memory, so they survive restarts and hold across instances: three per email
address and eight per IP address per hour. The IP address is erased as soon as
the application is confirmed.

### 4.3 Configuration hardening and throttling (`4696c55`, `beef360`)

- Sign-in throttling: six failures per username and twenty per IP in fifteen
  minutes, checked **before** the password so a lockout cannot be brute-forced
  past, and cleared on success.
- Password reset capped at five per IP per hour, always rendering the same
  confirmation page so neither form reveals who has an account.
- All throttling **fails open** if its cache table is missing: a forgotten
  table degrades protection rather than locking every user out.
- The Django admin moved off `/admin/` to a configurable path.
- Startup guards: with `DEBUG` off, a missing `SECRET_KEY` or an empty
  `DJANGO_ALLOWED_HOSTS` raises rather than starting. A deploy that fails
  loudly is better than one that silently signs sessions with a key published
  in the repository.

### 4.4 Upload validation (`4696c55`, later completed in `3b33d36`)

CV uploads are validated by **file signature** as well as by extension: a
`.pdf` that is not a PDF is refused. A malformed PDF previously returned HTTP
500; the file is now stored, the failure logged, and the person told it could
not be read.

### 4.5 Audit log (`1c84298`)

See §3.7.

### 4.6 Staff administration and departments (`14010a8`)

Staff account management was deliberately kept **out of the Django admin**:
those actions must follow the rules and be audited, and the admin would let a
superuser bypass both.

- Administrators create accounts; the work email is the username.
- The account starts with **no usable password**. The person sets their own
  from an emailed, single-use link valid for seven days. An administrator
  never knows a colleague's password.
- **Deactivate, never delete.** `is_active=False` plus session revocation.
  Feedback and audit history survive, and nobody else with the same role is
  affected.
- **The last administrator cannot be demoted or deactivated**, so the system
  cannot be locked out of its own administration.
- Staff sessions are eight hours of *idle* time; candidate sessions remain two
  weeks, because a candidate checking their application every few days should
  not be signed out.

### 4.7 Interview delegation (`8f6307a`)

See §3.6. The interview `interviewer` column was **renamed** rather than
recreated, so existing data survived the change.

### 4.8 Role gaps found by walkthrough (`94ebad0`)

The application was exercised as each of the seven staff roles in turn. That
found four real defects that no test had covered, including two roles missing
from the staff-group definition and therefore receiving HTTP 403 on the
dashboard.

---

## 5. Security work

### 5.1 Exposed database credential

The live database password, username and hostname had been committed to
`config/settings.py` in two commits. Remediation:

1. History was rewritten with `git filter-repo`, scrubbing all three values.
2. All four branches were force-pushed.
3. **It was then verified that the host still serves the original commits by
   their SHA**, which it does, and will until the provider purges them.

That verification is the important part. Rewriting history is not
remediation — it only removes the values from *reachable* commits. The
credential remains compromised until rotated, and the record says so plainly
rather than reporting the rewrite as a fix.

### 5.2 Static review findings, 2026-09-20

An independent review of the view layer produced five findings. Each was
verified against the code before action was taken; all five were accurate.

| Finding | Severity | Outcome |
|---|---|---|
| Staff CV upload skipped all validation | P1 | Fixed |
| Second upload view skipped signature check | P2 | View deleted |
| Interviews not department-scoped outside the dashboard | P3 | Confirmed intentional |
| Any staff account can open any CV | P3 | Access kept, auditing added |
| Rate limiting covers sign-in and reset only | P3 | Accepted; authenticated surface only |

**P1 detail.** The staff "Screen CV" button went directly from
`request.FILES` to storage with no size cap, no extension check and no
signature check — the exact thing the shared upload module exists to prevent,
and which both candidate-facing paths already called. A submission with no
file created a database row with no file at all. All three upload paths now
call the same validator.

Three further defects were found in the same area while fixing it:

- The staff upload page told recruiters the score passed or failed an
  application automatically. That had not been true since screening became a
  human decision. A test guarded the *public* copy against this claim; nothing
  guarded the staff page, which is where it actually misleads someone.
- The file picker offered `.doc`, which the server has never accepted.
- The DOCX file signature was listed twice instead of listing both valid ZIP
  signatures.

**On the two P3 scoping items.** Both were confirmed as deliberate and are now
recorded as such in `CLAUDE.md`, marked "do not fix". The reasoning is the same
in each case: recruiters and reviewers work across departments, and rounds get
covered at short notice. A restriction that breaks legitimate work is not a
security control, it is an outage. Accountability comes from the audit record
instead — which is why CV downloads are now logged.

---

## 6. Deployment

### 6.1 Shape, and why

One Elastic Beanstalk **single-instance** environment with **CloudFront in
front** for HTTPS, in `ap-southeast-1`.

**There is no custom domain.** AWS will not issue a certificate for
`*.elasticbeanstalk.com`, because AWS owns that domain — so the Beanstalk
hostname cannot serve HTTPS at all. CloudFront supplies both a hostname and a
free managed certificate, and its free tier is perpetual. That is the only
reason CloudFront is in this design; it is not for performance.

**There is no load balancer.** An Application Load Balancer costs more per
month than every other component combined. With a single instance it buys
nothing this project needs.

### 6.2 Scheduled housekeeping

Three management commands do work nothing else does:

| Command | Frequency | Consequence if it never runs |
|---|---|---|
| `expire_delegations` | Hourly | An interview arrives with nobody expecting to run it |
| `purge_pending_applications` | Weekly | The privacy notice's deletion promise is not kept |
| `purge_audit_events` | Weekly | The audit table grows without bound |

**`cron.yaml` is the wrong tool here**, and this is worth recording because it
is a natural first guess. Elastic Beanstalk periodic tasks exist only on
*worker* environments, where the daemon makes an HTTP request to the
application rather than running a command. This is a web tier, so a `cron.yaml`
would do nothing at all — silently, which is the worst possible failure mode
for jobs whose entire purpose is deleting data that was promised to be deleted.

`.ebextensions/cron.config` installs a real crontab instead. Three details
matter:

- **cron has none of the environment properties.** The deploy snapshots the
  deployment environment file, which exists only during a deploy, to a
  root-readable copy. Without it a job would run against the development
  settings rather than the real database.
- **Output is logged** with a start line and an exit status per run, rotated
  weekly. A job that fails silently is no better than one that never runs.
- **`config/test_deployment.py` asserts the schedule and the scripts still
  name real management commands**, so renaming a command cannot quietly stop
  the deletions.

### 6.3 Problems found during deployment

Four faults were found, in order. Each is recorded with its cause, because
each was invisible from where you would naturally look.

**1. The local environment file had drifted.** When the production guards were
added, the variables became `DJANGO_DEBUG` and `DJANGO_ALLOWED_HOSTS`, but the
local file still used the older bare names. Both were therefore unset, `DEBUG`
evaluated to `False`, the startup guard fired, and the application would not
boot at all. The template reproduced the same fault, because it defined
`DJANGO_ALLOWED_HOSTS` twice with the empty definition last — and `dotenv`
keeps the last value it sees.

Both are now covered by tests: one fails on a duplicate key in the template,
the other on any variable the settings module reads that the template never
mentions.

**2. Line endings.** The development machine has `core.autocrlf` enabled, so
the housekeeping scripts and the Beanstalk configuration files were being
checked out with CRLF endings. A shell script with CRLF fails on Amazon Linux
with `bad interpreter`, and a container command picks up a trailing carriage
return. One of the configuration files had *already* been shipping this way.
Fixed with `.gitattributes` forcing LF on the files that execute on Linux.

**3. The production application had never used the production database.** The
environment had all five database variables set, but not `DATABASE_URL` — and
the settings module selects PostgreSQL on the *presence* of that variable
alone. All five values were therefore read by nothing, and the application had
been running on a SQLite file on the instance, destroyed and recreated by
every deploy, while the real database was used only by local development.

The proof that this is now fixed is in the deploy log: the migration step
reported **"No migrations to apply"**. A fresh SQLite file would have applied
all thirty.

**4. The instance was running the wrong IAM identity.** The first deploy failed
with `logs:CreateLogStream` denied, and the denial named a role nobody
expected: a custom profile holding only `AmazonS3FullAccess`.

Someone had attached that profile **directly to the EC2 instance**, bypassing
Elastic Beanstalk. Beanstalk's own setting still named the standard role, so
the console displayed the correct answer while the instance used something
else. Without the standard Beanstalk web-tier policy the instance could not
report health *or* create log streams.

One cause, three symptoms:

- the deploy failure,
- a health status of "No Data" that had persisted for 46 days,
- and an S3 permission fix that had been applied to a role the instance was
  not using.

All three were resolved by reassociating the correct instance profile. **If
health ever goes quiet again, compare the instance's actual profile against
the environment's configured one before anything else** — they are permitted
to disagree, and nothing warns you.

### 6.4 Deployment outcome, 2026-09-20

The application was deployed, replacing a version that was thirty commits and
seven weeks behind. Environment health reached **Green / Ok**.

Verified after deployment:

| Check | Result |
|---|---|
| Landing, staff sign-in, candidate sign-in, careers | HTTP 200, correct pages |
| `/admin/` | HTTP 404 — successfully relocated |
| Relocated admin path | HTTP 302 to sign-in |
| `/healthz/` over plain HTTP | HTTP 200 — exempt, as designed |
| `/` over plain HTTP | HTTP 301 to HTTPS |
| Stylesheet | HTTP 200, correct content type |
| `collectstatic` | 136 files copied, 402 post-processed |
| `migrate` | "No migrations to apply" |

### 6.5 The HTTPS layer

Two pieces of middleware support the CloudFront design, and both exist for
reasons that are not obvious:

**`HealthCheckMiddleware`** answers `/healthz/` before the `Host` header is
validated. A load balancer checks its targets by address, so the request
arrives with `Host` set to the instance's private IP — which can never be in
`ALLOWED_HOSTS` and is unknowable in advance. Django would answer HTTP 400,
the target would read as unhealthy, and the environment would cycle instances
while every setting looked correct.

**`CloudFrontOriginMiddleware`** refuses any request that did not arrive
through CloudFront, comparing a shared secret in constant time. Without it the
Beanstalk hostname would serve the entire site over plain HTTP and the
certificate would be decorative. The health check never reaches this
middleware, and a test asserts that — because otherwise every deploy would
roll back.

CloudFront caching is **disabled** on the default behaviour. Every page in
this application is specific to the signed-in user, and a cached one would be
served to the wrong person. Only `/static/*` is cached, which is safe solely
because every static filename already contains a content hash.

**Current status: in progress.** The distribution is created and reaching the
origin, but the site is in a redirect loop — Django does not yet see requests
as encrypted, so it redirects to HTTPS and arrives back at itself. The
diagnosis is that the protocol header is not reaching the application. This
was deliberately found *before* the origin lock was enabled; with the lock on,
this fault and three others would have produced identical HTTP 403 responses.

---

## 7. Testing

**357 tests, all passing** as of 2026-09-20.

Tests are run against local SQLite by overriding the database URL. The real
database is never used for tests.

The suite is weighted towards the things that would be expensive to get wrong:

- **Access control**, including a regression test for every route a candidate
  account must not reach.
- **Delegation authorisation**, on both GET and POST for every transition.
- **Portal isolation**, asserting no portal route accepts a record identifier.
- **Upload validation**, asserting that a rejected file produces **no database
  row** — not merely that an error is displayed, since a validation failure
  that still writes to storage would otherwise pass.
- **Deployment wiring**, asserting the schedule names real commands, the
  environment template has no duplicate keys, and the health check answers on
  an unknown host while every other path still rejects one.
- **Public copy**, asserting that claims on the public site match the code.

The notification Lambda carries its own separate test suite.

---

## 8. Current state

| Area | State |
|---|---|
| Application code | Deployed, current, 357 tests passing |
| Environment health | Green / Ok |
| Database | RDS PostgreSQL, confirmed in use, all migrations applied |
| Static files | Collected and served |
| Scheduled housekeeping | Installed on deploy |
| HTTPS via CloudFront | **In progress** — redirect loop under diagnosis |
| Origin lock | Not yet enabled — deliberately, until HTTPS works |
| Email | **Not configured** — see §9 |

### Infrastructure facts

- Region `ap-southeast-1` throughout: application, database and object storage.
- Single-instance environment, `t3.micro`, Python 3.13 on Amazon Linux 2023.
- Database: PostgreSQL 18.3, `db.t3.micro`, single-AZ, 20 GiB, encrypted at
  rest, deletion protection **enabled**, one-day backup retention.
- The database is publicly accessible, restricted by security group to the
  application instance and one development address.
- Object storage holds CVs; versioning is disabled.
- CloudWatch log retention capped at seven days.

### Cost position

Spend is fully absorbed by promotional credit, with roughly $74 remaining
against a run rate of approximately $38 per month — a little under two months.
The database is about 60% of it.

A zero-spend budget alert is in place. The pre-existing budget alerted only at
$50 of spend, which on a credit-funded account would have stayed silent until
most of the balance was gone.

---

## 9. Outstanding work

### Blocking a usable site

1. **Finish the HTTPS layer.** The redirect loop must be resolved before the
   site is reachable in a browser.
2. **Enable the origin lock** once HTTPS works, closing the plain-HTTP path to
   the origin.

### Blocking a functional site

3. **Configure email.** The notification stack has never been deployed. Until
   it is, nobody can confirm an application, accept an invitation, or reset a
   password — the signup flow does not complete.

   Deploying email **after** the HTTPS layer is deliberate, not incidental.
   Every emailed link is built from the host the request arrived on, and
   invitation links live for seven days. Sending mail before the CloudFront
   hostname is in place would post links that stop working the moment the
   origin lock is enabled.

   Without a custom domain, a sender *address* can be verified but DKIM and
   SPF cannot be configured, so deliverability to external recipients will be
   poor regardless of sending limits. For demonstration with known, verified
   recipients this is sufficient; for real public signups it is not.

### Security

4. **Rotate the exposed database credential.** It remains readable in the
   repository host's history by commit SHA. Not optional.
5. **Request removal of the two affected commits** from the repository host.

### Housekeeping

6. Contact addresses remain non-routable placeholders. They appear on the
   privacy and security pages and in `security.txt`.
7. The object storage bucket name, which embeds the account identifier, is a
   hard-coded fallback in settings rather than environment-only.
8. The `ui-redesign` branch has never been merged to `main`.
9. Multi-factor authentication and single sign-on are deferred by agreement.
   Staff authentication was built with local passwords behind a seam that
   would accommodate SSO later.

---

## 10. Decisions register

Choices that could be mistaken for oversights. Each was made deliberately and
should not be "fixed" without revisiting the reasoning.

| Decision | Reasoning |
|---|---|
| Feedback is not restricted to the assigned interviewer | Rounds get covered at short notice, and every entry records its author |
| Interviews are not department-scoped outside the dashboard | Same reasoning; a scope that breaks legitimate work is an outage, not a control |
| Any staff account may open any CV | Recruiters and reviewers work across departments; accountability is the audit record |
| The Candidate group holds no permissions | The portal scopes by the linked record instead, so none are needed |
| Duplicate applications are detected at confirmation, not submission | Detecting at submission would leak who is in the pipeline |
| Throttling fails open when its cache is missing | Degraded protection beats locking every user out |
| Cross-department delegation is allowed and flagged | Blocking it would prevent legitimate cover arrangements |
| No load balancer | Costs more than every other component combined and buys nothing at one instance |
| CloudFront caching disabled by default | Every page is user-specific; a cached page would reach the wrong person |
| Python 3.13 rather than Django's officially supported 3.12 | The platform branch cannot be changed in place, and development runs 3.13 with the full suite passing |
