from notifier import audit


def test_log_attempt_writes_expected_shape(audit_table):
    audit.log_attempt(
        notification_id="abc-123",
        sent_at="2026-09-10T09:15:00+00:00",
        recipient="jane.doe@example.com",
        event_type="application_status_changed",
        status="SENT",
        ses_message_id="ses-msg-1",
    )

    items = audit_table.scan()["Items"]
    assert len(items) == 1
    item = items[0]
    assert item["notification_id"] == "abc-123"
    assert item["sent_at"] == "2026-09-10T09:15:00+00:00"
    assert item["status"] == "SENT"
    assert item["ses_message_id"] == "ses-msg-1"
    assert "error_message" not in item


def test_log_attempt_failure_includes_error_message(audit_table):
    audit.log_attempt(
        notification_id="abc-456",
        sent_at="2026-09-10T09:16:00+00:00",
        recipient="jane.doe@example.com",
        event_type="interview_scheduled",
        status="FAILED",
        error_message="SES send failed (Throttling): boom",
    )

    items = audit_table.scan()["Items"]
    assert items[0]["status"] == "FAILED"
    assert "error_message" in items[0]
    assert "ses_message_id" not in items[0]


def test_multiple_attempts_for_same_notification_id_are_both_kept(audit_table):
    """Retries of one logical event share notification_id but get distinct
    sent_at sort keys, so the full retry history is queryable together."""
    audit.log_attempt(
        notification_id="same-id",
        sent_at="2026-09-10T09:00:00+00:00",
        recipient="jane.doe@example.com",
        event_type="application_status_changed",
        status="FAILED",
        error_message="throttled",
    )
    audit.log_attempt(
        notification_id="same-id",
        sent_at="2026-09-10T09:05:00+00:00",
        recipient="jane.doe@example.com",
        event_type="application_status_changed",
        status="SENT",
        ses_message_id="ses-msg-2",
    )

    items = audit_table.scan()["Items"]
    assert len(items) == 2
