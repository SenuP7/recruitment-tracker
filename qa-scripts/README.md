# Candidflow QA automation (Playwright)

End-to-end browser tests for Candidflow's six core features. Each run starts
its own isolated copy of the app, drives it in Chromium the way a person
would, and shuts it down again.

**42 tests · about 70 seconds · no cleanup needed between runs.**

## The six features

| # | Spec | What it proves |
|---|---|---|
| 1 | `01-authentication.spec.ts` | Both sign-in doors work and refuse each other's accounts; a wrong password and an unknown user get identical messages; every role signs in; Administrator and Chief hold real permissions; signed-out visitors see nothing; logging out ends the session |
| 2 | `02-public-application.spec.ts` | Careers pages, field-by-field validation, fake-PDF rejection, no enumeration of existing applicants, and the **full journey**: apply → invisible to recruiters → confirm from the email → set a password → portal |
| 3 | `03-candidate-portal.spec.ts` | Candidates see their own application and progress, **never** feedback, scores, interviewer names or delegation details, get a 404 for anyone else's application, and are kept out of every staff page |
| 4 | `04-recruiter-pipeline.spec.ts` | Candidate list, search, stage tabs, the application record, CSV export that matches the screen, the duplicate-email guard, and a role that can read but not add |
| 5 | `05-cv-screening.spec.ts` | Scores are shown and genuinely differ, each result explains itself, only a recruiter is offered the outcome decision, and it can be made once |
| 6 | `06-interviews-feedback.spec.ts` | Interview list, the feedback thread, posting a reply, and delegation: pending stays with the owner, declining needs a reason, accepting hands over the round |

## Running it from VS Code (the Playwright extension)

One-time setup, in a terminal:

```bash
cd qa-scripts
npm install
npx playwright install chromium
```

Then in VS Code:

1. Install **Playwright Test for VSCode** (publisher: Microsoft).
2. Open the **Testing** panel (the flask icon in the sidebar). It finds
   `qa-scripts/playwright.config.ts` on its own and lists the six specs.
3. Press ▶ next to a feature, a single test, or the whole suite.
4. Tick **Show browser** in the Playwright section of the Testing panel to
   watch the tests drive Chromium.

The extension starts the QA server automatically before the first test —
there is nothing to launch by hand.

## Running it from a terminal

```bash
cd qa-scripts
npm test                  # everything, headless
npm run test:headed       # everything, with the browser visible
npm run test:ui           # Playwright's interactive UI mode
npx playwright test tests/03-candidate-portal.spec.ts   # one feature
npm run report            # open the HTML report from the last run
```

A failing test keeps a screenshot, a video and a full trace in
`test-results/`. Open a trace with `npx playwright show-trace <path>`.

## What it does NOT touch

`server/run_qa_server.py` starts Candidflow with `server/qa_settings.py`,
which overrides only what must never be shared with a real environment:

| Real setting | In QA |
|---|---|
| `db.sqlite3` (your dev database) or RDS Postgres | `qa-scripts/.qa-data/<port>/qa.sqlite3`, **reset to the same demo data at the start of every run** |
| S3 — which the app uses even locally | local disk, `qa-scripts/.qa-data/<port>/media/` |
| SQS → Lambda → SES | local mode: emails rendered to `local_notifications/`, which is how the suite reads the confirmation link |

`config/settings.py` is not modified. The server refuses port 8000, which is
reserved for your own server against the real database.

**Every run starts from the same data**, however it's launched.
`support/fixtures.ts` runs `server/reset_qa_data.py` once at the start of each
run: it empties every table, clears the sign-in throttling cache, and loads
`manage.py seed_demo --with-permissions` (the production permission matrix).

That matters because **VS Code's extension keeps one QA server running across
many runs** when *Show browser* is on — a reset tied to server start would
happen once, and the second run would find a screening outcome already
decided and a delegation already answered. So you can run one test, one
feature, or everything, in any order, as often as you like.

Every spec imports `test` and `expect` from `../support/fixtures`, not from
`@playwright/test`; a new spec must do the same, or it will skip the reset.

## Defects this suite found (both fixed)

1. **Signed-out visitors got a bare 403 on some staff pages.** Candidates,
   applications, positions and interviews answered an anonymous visitor with
   `403 Forbidden` and no sign-in link, because Django's
   `PermissionRequiredMixin(raise_exception=True)` applies to anonymous users
   too. With an 8-hour idle timeout, every bookmark became a dead end. Fixed
   with `accounts.mixins.PermissionRequiredMixin`, which sends signed-out
   visitors to sign in and keeps the 403 for signed-in users without the
   permission; that 403 now has a proper page (`templates/403.html`).
2. **`seed_demo --with-permissions` left Department Chief and Administrator
   with zero permissions.** It kept its own copy of the permission matrix,
   which had drifted from `assign_role_permissions`. It now runs
   `assign_role_permissions` itself, so there is one matrix.

Both have Django unit tests as well (`accounts/test_sign_in_redirects.py`,
`candidates/test_seed_demo.py`), and Feature 1 here covers both.

## Screenshots for a report

Every test keeps a screenshot of its final screen, pass or fail
(`screenshot: 'on'` in `playwright.config.ts`). After a run:

```bash
npm run report
```

opens the HTML report; click any test to see its screenshot under
**Attachments**. The image files themselves are in `test-results/`.

## Settings you can change

| Environment variable | Default | Purpose |
|---|---|---|
| `QA_PORT` | `8001` | Port for the QA server |
| `QA_PYTHON` | `../venv` interpreter | Python to run Django with |
| `CANDIDFLOW_DEMO_PASSWORD` | `Qa-Candidflow-2026!` | Password for every seeded account |

Tests run one at a time on purpose (`workers: 1`): they share one database
and several of them change it.
