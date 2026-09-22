"""Puts the QA database back to a known state. Runs before every test run.

Why per run and not per server start: VS Code's Playwright extension keeps
one QA server alive across many runs, so a reset tied to server start
happens once and then never again. Several tests change state that can only
change once -- a screening outcome is decided once, a delegation is answered
once -- and the public application form is rate limited per IP *in the
database*. Without this, a second run fails for reasons that have nothing to
do with the code under test.

What it does:
  - empties every table (the server can stay running; SQLite allows it),
  - clears the cache table, which holds sign-in throttling counters and is
    not a model table, so flush leaves it alone,
  - deletes uploaded CVs from earlier runs (best effort -- see below),
  - loads seed_demo with --with-permissions (the production role matrix).
"""

import os
import shutil

import qa_env  # noqa: F401 -- must come first: sets the isolated environment


def main():
    import django
    from django.core.cache import cache
    from django.core.management import call_command

    django.setup()

    call_command("flush", interactive=False, verbosity=0)
    cache.clear()
    # Best effort. On Windows a file the running server still has open (a CV
    # it just scored) cannot be deleted, and failing the reset over it would
    # stop the whole run. A leftover upload is harmless: every upload gets a
    # unique name, nothing refers to it after the flush, and the folder is
    # removed outright whenever the server restarts.
    shutil.rmtree(qa_env.MEDIA, ignore_errors=True)

    with open(os.devnull, "w") as quiet:
        call_command(
            "seed_demo",
            with_permissions=True,
            base_url=f"http://127.0.0.1:{qa_env.PORT}",
            stdout=quiet,
        )
    print("[qa] test data reset", flush=True)


if __name__ == "__main__":
    main()
