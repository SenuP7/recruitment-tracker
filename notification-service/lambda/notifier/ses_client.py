"""Thin wrapper around SES SendEmail that classifies failures as transient
(worth retrying via SQS redelivery) or permanent (poison pill -- don't retry).
"""

import os

import boto3
from botocore.exceptions import ClientError

# Error codes SES/botocore raise for throttling/outages -- worth retrying.
# Anything else (MessageRejected for an unverified/invalid address in SES sandbox,
# MailFromDomainNotVerifiedException, etc.) is treated as permanent.
_TRANSIENT_ERROR_CODES = {
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailable",
    "InternalFailure",
    "RequestTimeout",
}


class SESSendError(Exception):
    def __init__(self, message, transient):
        super().__init__(message)
        self.transient = transient


def send_email(recipient_email, subject, body):
    sender_email = os.environ.get("SES_SENDER_EMAIL", "")
    if not sender_email:
        raise SESSendError("SES_SENDER_EMAIL environment variable not configured", transient=False)

    client = boto3.client("ses")
    try:
        response = client.send_email(
            Source=sender_email,
            Destination={"ToAddresses": [recipient_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
        return response["MessageId"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        transient = code in _TRANSIENT_ERROR_CODES
        raise SESSendError(f"SES send failed ({code}): {exc}", transient=transient) from exc
