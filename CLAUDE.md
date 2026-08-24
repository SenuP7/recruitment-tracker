# Recruitment Tracker — session notes

Internal Django recruitment tracker. Six roles via Django Groups: Recruiter,
HR Interviewer, Technical Interviewer, Senior Reviewer, Leadership Manager,
Candidate. Apps: `accounts`, `candidates`, `positions`, `cv_screening`,
`interviews`, `notifications` (stub, no views/urls — unused), `dashboard`.

## Commit message convention

**Never add `Co-Authored-By` or `Claude-Session` trailers to commits.** User
preference, stated explicitly — plain descriptive commit messages only.

## Testing

Use `DATABASE_URL="" python manage.py test` — the real `DATABASE_URL` points
at a remote Postgres that hangs trying to create a throwaway test database
there. The empty override falls back to local SQLite (fast, safe, doesn't
touch the real DB).

## What's been built this session

**1. Full visual redesign** — Stripe-inspired design system from scratch.
`templates/base.html` is a shared nav shell (didn't exist before — every
page used to be a disconnected standalone HTML file); all 27 templates now
extend it. Status badges use `data-status="{{ value }}"` attributes matched
against exact model choice strings in CSS — no template logic added, just
attribute output.

**2. `dashboard` app** — built from scratch, RBAC-secured, HTMX-filtered.
See `dashboard/CLAUDE.md`.

Two real pre-existing bugs (logout broken, CV screening had zero access
control) were also fixed this session — see the docstrings in
`accounts/tests.py` and `cv_screening/tests.py` (`CVScreeningAccessControlTests`)
for the full root-cause writeups.

## RBAC / permissions — current correct state (2026-08-20)

Groups and their Django permissions are managed **by hand** in this project
(via admin/shell), never via migration or fixture — there's no code
representation of "what a group should have," so DB state is the source of
truth. Check it directly before assuming:

```python
from django.contrib.auth.models import Group
for g in Group.objects.all():
    print(g.name, [f'{p.content_type.app_label}.{p.codename}' for p in g.permissions.all()])
```

**Candidate group** currently has: `candidates.view_application`,
`candidates.view_candidate`, `interviews.view_interview`,
`interviews.view_interviewfeedback`, `positions.view_position`.

Story behind that, in order:
1. Audited every view for the same "gated only by login_required" gap CV
   screening had — found none elsewhere; all `candidates`/`positions`/
   `interviews` CRUD views already use `PermissionRequiredMixin` correctly.
2. **Mistake**: over-corrected by stripping *all four* of the Candidate
   group's `view_*` permissions, intending to stop candidates seeing
   *other* candidates' data — this instead left them unable to see
   anything, including their own profile info. User caught it immediately.
3. **Reverted**: `git revert` (commit `71ae719`) undid the code/template
   changes; DB permissions manually restored to match. Confirmed back to
   the exact pre-mistake baseline (46/46 tests).
4. **Separately, a real and different gap**: Candidate group never had
   `positions.view_position` at all (unrelated to the above mistake, just
   never granted). Added it — candidates can now browse open positions
   (`PositionListView.get_queryset()` already filters to `is_open=True`
   only, so this doesn't leak closed positions).

**⚠️ Known real gap, flagged but NOT built yet:** there is no link between
a Django `User` and a `Candidate` model record anywhere in this codebase.
So "Candidate group can view_candidate" currently means they can see
**every** candidate/application/interview/feedback record, not just their
own — there's no "own record" concept to scope to yet. Fixing this properly
needs:
- An FK from `Candidate` back to `User` (nullable — most `Candidate` rows
  won't have a linked login)
- Queryset scoping in the candidate/application/interview list & detail
  views: when `request.user` is in the Candidate group, filter down to
  their own linked record instead of the current all-or-nothing permission
  check
- Decide interview/feedback visibility scope for a candidate (their own
  interviews only, presumably — not discussed yet)

This is a real feature to design and build, not a quick permission tweak.
Was mid-discussion on this when the session was summarized — pick up here.

## Two DB-only changes this session (not visible in `git diff`)

Because groups/permissions are hand-managed, not migration-managed, these
won't show up in git history — noted here so they aren't lost:
- Candidate group permissions (see above — net effect after the
  strip/revert/re-fix cycle: same four `view_*` as before, plus the new
  `positions.view_position`)
- A handful of throwaway `__*_check__`/`__*_preview__` test accounts were
  created and deleted during verification each time — none should remain
  in the database. If one is ever found lingering, it's leftover from a
  verification session and safe to delete.
