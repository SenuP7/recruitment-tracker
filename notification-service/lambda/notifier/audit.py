"""DynamoDB audit-log writer. notification_id is the partition key, sent_at (ISO8601)
the sort key -- every attempt (including retries of the same logical event) gets its
own item, so querying by notification_id shows the full retry history.
"""

import os

import boto3

_table = None
_table_name = None


def _get_table():
    global _table, _table_name
    table_name = os.environ.get("AUDIT_TABLE_NAME", "recruitment-tracker-notifications-audit")
    if _table is None or _table_name != table_name:
        _table = boto3.resource("dynamodb").Table(table_name)
        _table_name = table_name
    return _table


def log_attempt(notification_id, sent_at, recipient, event_type, status, error_message=None, ses_message_id=None):
    item = {
        "notification_id": notification_id,
        "sent_at": sent_at,
        "recipient": recipient,
        "event_type": event_type,
        "status": status,
    }
    if error_message:
        item["error_message"] = error_message
    if ses_message_id:
        item["ses_message_id"] = ses_message_id
    _get_table().put_item(Item=item)
