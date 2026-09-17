"""SQS-triggered Lambda entry point.

The event source mapping (template.yaml) uses BatchSize: 1 deliberately -- with a
larger batch, one message's exception would fail the whole batch and could cause
already-sent emails (for other messages in the same batch) to be retried and
double-sent, since this handler doesn't implement SQS's partial-batch-failure
reporting. BatchSize 1 sidesteps that entirely at negligible extra invocation cost
for a student-project message volume.

Two failure classes, handled differently:
  - Poison pill (malformed JSON, unknown event_type, missing template fields,
    permanent SES rejection): logged to DynamoDB as FAILED, function returns
    normally so SQS deletes the message -- retrying can't fix a malformed message.
  - Transient failure (SES throttling/outage): logged to DynamoDB as FAILED, then
    re-raised so SQS's visibility timeout expiry redelivers the message; after
    maxReceiveCount attempts it lands in the DLQ.
"""

import json
import logging
from datetime import datetime, timezone

from . import audit, templates
from .ses_client import SESSendError, send_email

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    for record in event.get("Records", []):
        _process_record(record)


def _process_record(record):
    try:
        message = json.loads(record.get("body", "{}"))
    except json.JSONDecodeError as exc:
        logger.error("Malformed SQS message body, treating as poison pill: %s", exc)
        _log_failure("unknown", "unknown", "unknown", error=f"JSON decode error: {exc}")
        return

    notification_id = message.get("notification_id", "unknown")
    event_type = message.get("event_type", "unknown")
    recipient = message.get("recipient_email", "unknown")
    context_data = message.get("context", {})

    try:
        subject, body = templates.render(event_type, context_data)
    except (templates.UnknownEventType, templates.MissingTemplateContext) as exc:
        logger.error("Poison pill for notification %s: %s", notification_id, exc)
        _log_failure(notification_id, recipient, event_type, error=str(exc))
        return

    try:
        ses_message_id = send_email(recipient, subject, body)
    except SESSendError as exc:
        _log_failure(notification_id, recipient, event_type, error=str(exc))
        if exc.transient:
            logger.warning(
                "Transient SES failure for %s, will retry via SQS: %s", notification_id, exc
            )
            raise
        logger.error("Permanent SES failure for %s, not retrying: %s", notification_id, exc)
        return

    _log_success(notification_id, recipient, event_type, ses_message_id)


def _log_success(notification_id, recipient, event_type, ses_message_id):
    try:
        audit.log_attempt(
            notification_id=notification_id,
            sent_at=_now(),
            recipient=recipient,
            event_type=event_type,
            status="SENT",
            ses_message_id=ses_message_id,
        )
    except Exception:
        logger.exception(
            "Failed to write success audit log for %s (email was still sent)", notification_id
        )


def _log_failure(notification_id, recipient, event_type, error):
    try:
        audit.log_attempt(
            notification_id=notification_id,
            sent_at=_now(),
            recipient=recipient,
            event_type=event_type,
            status="FAILED",
            error_message=error,
        )
    except Exception:
        logger.exception("Failed to write failure audit log for %s", notification_id)


def _now():
    return datetime.now(timezone.utc).isoformat()
