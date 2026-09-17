# Formal Test Cases — Notification Service

These are the report-facing, manually-executed test cases run against the real
deployed stack. Automated equivalents (moto-mocked, run via `pytest`) exist for
the ones marked **[automated]** below — see `tests/test_handler.py`,
`tests/test_templates.py`, `tests/test_audit.py`. TC-05 is inherently a real-AWS
integration test (CloudWatch alarm -> SNS delivery) and has no automated
equivalent.

---

### TC-01 — Successful send: application status change **[automated]**

- **Preconditions**: Stack deployed; SES sender identity verified; recipient
  address verified (sandbox mode); `NOTIFICATIONS_SQS_QUEUE_URL` set in Django's
  environment.
- **Steps**: In the Django app, change an `Application`'s `status` field (e.g.
  via the admin or the Application edit view) and save.
- **Expected result**: Recipient receives an email with the old/new status. A
  DynamoDB item exists for the event's `notification_id` with `status=SENT` and
  a populated `ses_message_id`.

### TC-02 — Successful send: interview scheduled **[automated]**

- **Preconditions**: Same as TC-01.
- **Steps**: Create a new `Interview` for an existing `Application`.
- **Expected result**: Recipient receives an email with interview type and
  date/time. DynamoDB item with `status=SENT` for that `notification_id`.

### TC-03 — SES transient failure triggers a retry **[automated]**

- **Preconditions**: Lambda deployed.
- **Steps**: Publish a message while SES is throttling (automated test:
  `notifier.ses_client.send_email` mocked to raise `SESSendError(transient=True)`).
- **Expected result**: The Lambda invocation raises (does not swallow the
  error); a DynamoDB item is written with `status=FAILED` and an
  `error_message`; SQS's visibility timeout expiry causes redelivery.

### TC-04 — Message exceeds maxReceiveCount and lands in the DLQ

- **Preconditions**: Stack deployed with `MaxReceiveCount=3` (default).
- **Steps**: Force 3 consecutive failed delivery attempts for one message (e.g.
  temporarily break the SES identity, or use the AWS CLI to inspect
  `ApproximateReceiveCount` after repeated failures).
- **Expected result**: After the 3rd failed attempt, the message no longer
  appears in the main queue; `aws sqs get-queue-attributes` on the DLQ shows
  `ApproximateNumberOfMessages >= 1`.

### TC-05 — DLQ depth triggers the CloudWatch alarm and SNS email

- **Preconditions**: TC-04 has produced at least one DLQ message; the alert
  email subscription is confirmed (one-time SNS confirmation click after first
  deploy).
- **Steps**: Wait up to 5 minutes (the alarm's evaluation period) after a
  message lands in the DLQ.
- **Expected result**: `recruitment-tracker-notifications-dlq-depth` alarm
  transitions to `ALARM` in the CloudWatch console; the subscribed address
  receives an SNS alert email.

### TC-06 — DynamoDB audit entry correctness on success **[automated]**

- **Preconditions**: A successful send has occurred (TC-01 or TC-02).
- **Steps**: Query the audit table by the event's `notification_id`.
- **Expected result**: Exactly one item with `status=SENT`, correct `recipient`,
  `event_type`, and a non-empty `ses_message_id`; no `error_message` attribute.

### TC-07 — DynamoDB audit entry correctness on failure **[automated]**

- **Preconditions**: A failed send has occurred (TC-03).
- **Steps**: Query the audit table by that event's `notification_id`.
- **Expected result**: An item with `status=FAILED` and a non-empty
  `error_message`; no `ses_message_id` attribute.

### TC-08 — Unknown/malformed event_type is a poison pill, not endlessly retried **[automated]**

- **Preconditions**: Lambda deployed.
- **Steps**: Publish a message with an `event_type` not present in
  `EVENT_TEMPLATE_REGISTRY` (or with required context fields missing).
- **Expected result**: The Lambda invocation returns normally (no exception); a
  DynamoDB item is written with `status=FAILED`; the message does **not**
  reappear in the queue and does **not** end up in the DLQ.

### TC-09 — Creating an Application does not fire a notification (Django-side)

- **Automated equivalent**: `candidates/tests.py::ApplicationStatusNotificationSignalTests::test_creating_application_does_not_publish`
- **Preconditions**: None.
- **Steps**: Create a new `Application` (initial status `"Applied"`).
- **Expected result**: `publish_event` is not called — only *transitions*
  trigger a notification, not the initial creation.

### TC-10 — Signal only publishes after transaction commit (Django-side)

- **Automated equivalent**: `candidates/tests.py::ApplicationStatusNotificationSignalTests::test_status_change_does_not_publish_if_transaction_rolls_back`
- **Preconditions**: None.
- **Steps**: Inside an `atomic()` block, change an `Application`'s status, then
  raise an exception before the block exits (forcing a rollback).
- **Expected result**: `publish_event` is never called — `transaction.on_commit`
  guarantees a rolled-back status change can never trigger an email for a
  change that, from the database's perspective, never happened.
