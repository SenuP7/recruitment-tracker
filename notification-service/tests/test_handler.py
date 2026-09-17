from unittest.mock import patch

import pytest

from notifier import handler
from notifier.ses_client import SESSendError

from .conftest import load_event


def test_successful_send_writes_sent_audit_entry(ses_verified_identity, audit_table):
    event = load_event("application_status_changed.json")
    handler.lambda_handler(event, None)  # must not raise

    items = audit_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "SENT"
    assert items[0]["event_type"] == "application_status_changed"
    assert items[0]["recipient"] == "jane.doe@example.com"
    assert "ses_message_id" in items[0]


def test_interview_scheduled_successful_send(ses_verified_identity, audit_table):
    event = load_event("interview_scheduled.json")
    handler.lambda_handler(event, None)

    items = audit_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "SENT"
    assert items[0]["event_type"] == "interview_scheduled"


def test_transient_ses_failure_is_reraised_for_sqs_retry(audit_table):
    """Covers TC-03/TC-04: a transient SES error must propagate out of the
    handler so SQS redelivers the message (eventually landing in the DLQ after
    maxReceiveCount) -- it must not be silently swallowed."""
    event = load_event("application_status_changed.json")
    with patch("notifier.handler.send_email", side_effect=SESSendError("throttled", transient=True)):
        with pytest.raises(SESSendError):
            handler.lambda_handler(event, None)

    items = audit_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "FAILED"
    assert "error_message" in items[0]


def test_permanent_ses_failure_is_not_retried(audit_table):
    event = load_event("application_status_changed.json")
    with patch("notifier.handler.send_email", side_effect=SESSendError("rejected", transient=False)):
        handler.lambda_handler(event, None)  # must not raise

    items = audit_table.scan()["Items"]
    assert items[0]["status"] == "FAILED"


def test_unknown_event_type_is_poison_pill_not_retried(audit_table):
    """Covers TC-08: an unrecognized event_type must be logged and dropped,
    not endlessly retried."""
    event = load_event("malformed_event.json")
    handler.lambda_handler(event, None)  # must not raise

    items = audit_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "FAILED"
    assert items[0]["event_type"] == "some_future_trigger_not_yet_supported"


def test_invalid_json_body_is_poison_pill_not_retried(audit_table):
    event = {"Records": [{"body": "not valid json {{{"}]}
    handler.lambda_handler(event, None)  # must not raise

    items = audit_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "FAILED"
    assert items[0]["notification_id"] == "unknown"
