"""Starts Candidflow for the Playwright suite, from nothing, every time.

Playwright's webServer runs this before any test. It deletes the previous
QA data, migrates a fresh SQLite file, loads seed_demo with a known password,
then serves on 127.0.0.1 (port 8001 unless QA_PORT says otherwise).

Starting clean is what makes the suite repeatable: the public application
form is rate limited per email and per IP *in the database*, a screening
outcome can only be decided once, and a delegation can only be answered
once. On a reused database the second run would fail for reasons that have
nothing to do with the code under test.

Never touches db.sqlite3, the real Postgres, S3, SQS or SES -- see
qa_settings.py for how.
"""

import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QA_ROOT = HERE.parent
REPO = QA_ROOT.parent
DATA = QA_ROOT / ".qa-data"

PORT = os.environ.get("QA_PORT", "8001")
if PORT == "8000":
    # 8000 is the developer's own server, pointed at the real database.
    sys.exit("Refusing to start the QA server on port 8000.")

# These must be set before Django reads settings. settings.py calls
# load_dotenv(), which never overrides a variable that is already present,
# so these win over whatever .env says.
os.environ["DATABASE_URL"] = ""  # empty: never take the Postgres branch
os.environ["DJANGO_DEBUG"] = "True"
os.environ["NOTIFICATIONS_LOCAL_MODE"] = "True"
os.environ["NOTIFICATIONS_SQS_QUEUE_URL"] = ""
os.environ["CLOUDFRONT_ORIGIN_SECRET"] = ""
os.environ["DJANGO_SETTINGS_MODULE"] = "qa_settings"
os.environ["CANDIDFLOW_QA_DATA"] = str(DATA)
os.environ.setdefault("CANDIDFLOW_DEMO_PASSWORD", "Qa-Candidflow-2026!")

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
os.chdir(REPO)


def main():
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)

    import django
    from django.core.management import call_command

    django.setup()

    print("[qa] migrating a fresh database...", flush=True)
    call_command("migrate", verbosity=0, interactive=False)
    call_command("createcachetable", verbosity=0)

    print("[qa] loading demo data...", flush=True)
    with open(os.devnull, "w") as quiet:
        call_command(
            "seed_demo",
            with_permissions=True,
            base_url=f"http://127.0.0.1:{PORT}",
            stdout=quiet,
        )
        # --with-permissions runs assign_role_permissions, the same matrix the
        # live site uses. (It used to keep a drifted copy that left Department
        # Chief and Administrator with nothing; this suite found that, and
        # Feature 1 fails if it ever comes back.)

    print(f"[qa] serving on http://127.0.0.1:{PORT}", flush=True)
    call_command("runserver", f"127.0.0.1:{PORT}", use_reloader=False)


if __name__ == "__main__":
    main()
