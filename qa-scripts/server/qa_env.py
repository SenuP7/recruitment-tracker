"""Shared bootstrap for everything that runs Django for the QA suite.

run_qa_server.py (starts the server) and reset_qa_data.py (resets the data
before every test run) both import this first, so the isolation below is
defined in exactly one place.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QA_ROOT = HERE.parent
REPO = QA_ROOT.parent

PORT = os.environ.get("QA_PORT", "8001")
if PORT == "8000":
    # 8000 is the developer's own server, pointed at the real database.
    sys.exit("Refusing to run QA on port 8000.")

# One folder per port. VS Code's Playwright extension keeps its QA server
# running between runs and so holds the database open; a second server
# sharing the folder could not reset it (WinError 32). Separate folders mean
# two instances can never collide.
DATA = QA_ROOT / ".qa-data" / PORT
MEDIA = DATA / "media"

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
