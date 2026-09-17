"""Local-dev stand-in for the real SQS -> Lambda -> SES -> DynamoDB pipeline.

Lets you exercise the full notification flow against `manage.py runserver` with
no AWS account at all. Reuses the exact same template-rendering code that ships
to the real Lambda (notification-service/lambda/notifier/templates.py) as the
single source of truth -- local-mode output matches what the real Lambda would
actually send, it's not a reimplementation.

Swaps SES for a local .txt file (+ console log) and DynamoDB for a local
JSON-lines audit file, both under BASE_DIR/local_notifications/ (gitignored).
"""

import json
import logging
import sys
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_LAMBDA_DIR = Path(settings.BASE_DIR) / "notification-service" / "lambda"
_OUTPUT_DIR = Path(settings.BASE_DIR) / "local_notifications"


def _notifier_templates():
    """Imports notifier.templates from notification-service/lambda/, adding it to
    sys.path on first use. Lazy/local import -- this dependency only exists for
    local-mode development, never in a real deploy (Django doesn't ship the
    notification-service/ tree)."""
    if str(_LAMBDA_DIR) not in sys.path:
        sys.path.insert(0, str(_LAMBDA_DIR))
    from notifier import templates

    return templates


def handle_locally(notification_id, event_type, recipient_email, recipient_name, context, occurred_at):
    """Renders the email via the real Lambda template registry, writes it to a
    local file, logs + prints it, and appends a DynamoDB-shaped audit record.
    Never raises -- mirrors publish_event's "never break the caller" contract.
    Returns True if the email was "sent" (rendered successfully), else False.
    """
    _OUTPUT_DIR.mkdir(exist_ok=True)

    try:
        templates = _notifier_templates()
        subject, body = templates.render(event_type, context)
        status, error_message = "SENT", None
    except Exception as exc:
        subject, body = None, None
        status, error_message = "FAILED", str(exc)

    if status == "SENT":
        email_path = _OUTPUT_DIR / f"{notification_id}.txt"
        email_path.write_text(
            f"To: {recipient_name} <{recipient_email}>\nSubject: {subject}\n\n{body}\n",
            encoding="utf-8",
        )
        logger.info(
            "[LOCAL NOTIFICATION] To: %s <%s> | Subject: %s | saved to %s",
            recipient_name, recipient_email, subject, email_path,
        )
        print(
            f"\n----- LOCAL NOTIFICATION ({event_type}) -----\n"
            f"To: {recipient_name} <{recipient_email}>\nSubject: {subject}\n\n{body}"
            f"-------------------------------------------\n"
        )
    else:
        logger.warning("[LOCAL NOTIFICATION] Failed to render %s: %s", event_type, error_message)

    _append_audit(notification_id, occurred_at, recipient_email, event_type, status, error_message)
    return status == "SENT"


def _append_audit(notification_id, sent_at, recipient, event_type, status, error_message):
    record = {
        "notification_id": notification_id,
        "sent_at": sent_at,
        "recipient": recipient,
        "event_type": event_type,
        "status": status,
    }
    if error_message:
        record["error_message"] = error_message

    audit_path = _OUTPUT_DIR / "audit_log.jsonl"
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
