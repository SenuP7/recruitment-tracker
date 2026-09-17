import json
import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

EVENTS_DIR = Path(__file__).resolve().parent.parent / "events"
AWS_REGION = "ap-southeast-1"


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """moto still wants *some* credentials present in the environment."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)
    monkeypatch.setenv("SES_SENDER_EMAIL", "notifications@example.com")
    monkeypatch.setenv("AUDIT_TABLE_NAME", "recruitment-tracker-notifications-audit")


@pytest.fixture
def aws(aws_credentials):
    with mock_aws():
        yield


@pytest.fixture
def ses_verified_identity(aws):
    client = boto3.client("ses", region_name=AWS_REGION)
    client.verify_email_identity(EmailAddress="notifications@example.com")
    client.verify_email_identity(EmailAddress="jane.doe@example.com")
    return client


@pytest.fixture
def audit_table(aws):
    resource = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = resource.create_table(
        TableName="recruitment-tracker-notifications-audit",
        KeySchema=[
            {"AttributeName": "notification_id", "KeyType": "HASH"},
            {"AttributeName": "sent_at", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "notification_id", "AttributeType": "S"},
            {"AttributeName": "sent_at", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def load_event(name):
    with open(EVENTS_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def load_message(event_file_name):
    """Convenience: parse the single record's body back into a dict for tests
    that want to construct variants of a sample message."""
    event = load_event(event_file_name)
    return json.loads(event["Records"][0]["body"])
