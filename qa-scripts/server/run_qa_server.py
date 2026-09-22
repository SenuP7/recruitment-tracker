"""Starts Candidflow for the Playwright suite.

Playwright's webServer runs this. It creates an empty, migrated SQLite
database and serves on 127.0.0.1 (port 8001 unless QA_PORT says otherwise).
It does NOT load test data: reset_qa_data.py does that at the start of every
test run, because the server's lifetime is not the run's lifetime -- VS
Code's Playwright extension keeps one server alive across many runs.

Never touches db.sqlite3, the real Postgres, S3, SQS or SES -- see
qa_env.py and qa_settings.py for how.
"""

import shutil

import qa_env  # noqa: F401 -- must come first: sets the isolated environment


def main():
    if qa_env.DATA.exists():
        shutil.rmtree(qa_env.DATA)
    qa_env.DATA.mkdir(parents=True)

    import django
    from django.core.management import call_command

    django.setup()

    print("[qa] migrating a fresh database...", flush=True)
    call_command("migrate", verbosity=0, interactive=False)
    call_command("createcachetable", verbosity=0)

    print(f"[qa] serving on http://127.0.0.1:{qa_env.PORT}", flush=True)
    call_command("runserver", f"127.0.0.1:{qa_env.PORT}", use_reloader=False)


if __name__ == "__main__":
    main()
