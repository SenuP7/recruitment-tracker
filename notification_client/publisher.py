"""Publishes notification events to the SQS queue consumed by the notification-service
Lambda. Must never let a boto3/SQS failure break the caller's request cycle -- every
failure is caught, logged, and reported back as a bool rather than raised.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import boto3
from django.conf import settings

logger = logging.getLogger(__name__)


def publish_event(event_type, recipient_email, recipient_name, context):
    """Publish one notification event.

    In local mode (NOTIFICATIONS_LOCAL_MODE=True), runs the real Lambda template
    rendering in-process and writes the result under local_notifications/ instead
    of touching AWS at all -- see notification_client/local_runner.py.

    Otherwise publishes to SQS. Returns True if accepted, False otherwise
    (including when notifications aren't configured at all -- a safe no-op for
    environments with no AWS access, e.g. a laptop with no AWS credentials).
    """
    notification_id = str(uuid.uuid4())
    occurred_at = datetime.now(timezone.utc).isoformat()

    if settings.NOTIFICATIONS_LOCAL_MODE:
        from notification_client.local_runner import handle_locally

        return handle_locally(
            notification_id, event_type, recipient_email, recipient_name, context, occurred_at
        )

    queue_url = settings.NOTIFICATIONS_SQS_QUEUE_URL
    if not queue_url:
        logger.warning(
            "NOTIFICATIONS_SQS_QUEUE_URL not configured; dropping %s event", event_type
        )
        return False

    message = {
        "notification_id": notification_id,
        "event_type": event_type,
        "recipient_email": recipient_email,
        "recipient_name": recipient_name,
        "context": context,
        "occurred_at": occurred_at,
    }

    try:
        client = boto3.client("sqs", region_name=settings.NOTIFICATIONS_AWS_REGION)
        client.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))
        return True
    except Exception:
        logger.exception("Failed to publish notification event: %s", event_type)
        return False
