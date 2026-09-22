"""Django settings for the Playwright QA suite.

Imports the real settings and overrides only what must never be shared with a
real environment. config/settings.py itself is untouched.

Why each override exists:

- DATABASES: settings.py hardcodes local SQLite to db.sqlite3, which is the
  developer's own database. The suite creates candidates, confirms
  applications and posts feedback, so it gets a throwaway file that
  run_qa_server.py deletes before every run.
- STORAGES["default"]: settings.py always uses S3, even locally, so a test
  that uploads a CV would write into the real production bucket. Local disk
  instead, inside the same throwaway folder.
- Notifications: local mode only. Emails are rendered to local_notifications/
  (which is how the suite reads the confirmation link) and nothing reaches
  SQS or SES.
"""

import os
from pathlib import Path

from config.settings import *  # noqa: F401,F403
from config.settings import STORAGES as _BASE_STORAGES

_DATA = Path(os.environ["CANDIDFLOW_QA_DATA"])

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _DATA / "qa.sqlite3",
    }
}

MEDIA_ROOT = _DATA / "media"
MEDIA_URL = "/qa-media/"
STORAGES = {
    **_BASE_STORAGES,
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(MEDIA_ROOT), "base_url": MEDIA_URL},
    },
}

NOTIFICATIONS_LOCAL_MODE = True
NOTIFICATIONS_SQS_QUEUE_URL = ""

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
