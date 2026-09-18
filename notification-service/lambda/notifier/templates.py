"""Event-type -> email template registry.

Adding a new trigger later = one new TemplateSpec entry + one new .txt body file.
No change to handler.py's dispatch logic is ever needed.
"""

import os
from dataclasses import dataclass

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "email_templates")


@dataclass(frozen=True)
class TemplateSpec:
    subject_template: str
    body_file: str
    required_fields: tuple


EVENT_TEMPLATE_REGISTRY = {
    "application_status_changed": TemplateSpec(
        subject_template="Update on your application for {job_title}",
        body_file="application_status_changed.txt",
        required_fields=("candidate_name", "job_title", "old_status", "new_status"),
    ),
    "interview_scheduled": TemplateSpec(
        subject_template="Interview Scheduled - {job_title}",
        body_file="interview_scheduled.txt",
        required_fields=("candidate_name", "job_title", "interview_type", "scheduled_date"),
    ),
    "application_confirm": TemplateSpec(
        subject_template="Confirm your application for {job_title}",
        body_file="application_confirm.txt",
        required_fields=("candidate_name", "company_name", "job_title", "confirm_url", "expires_at"),
    ),
    "staff_invite": TemplateSpec(
        subject_template="Set up your {company_name} account",
        body_file="staff_invite.txt",
        required_fields=("recipient_name", "company_name", "setup_url", "expires_at"),
    ),
    "portal_invite": TemplateSpec(
        subject_template="Set up your {company_name} account",
        body_file="portal_invite.txt",
        required_fields=("candidate_name", "company_name", "invite_url", "expires_at"),
    ),
    "password_reset": TemplateSpec(
        subject_template="Reset your {company_name} password",
        body_file="password_reset.txt",
        required_fields=("recipient_name", "company_name", "reset_url", "valid_hours"),
    ),
}


class MissingTemplateContext(Exception):
    """Raised when the event's context dict is missing a field the template needs.
    Treated as a poison pill by the handler -- retrying can't fix a malformed message.
    """


class UnknownEventType(Exception):
    """Raised when event_type has no registry entry. Also a poison pill."""


def render(event_type, context):
    """Returns (subject, body) for the given event_type and context dict.

    Raises UnknownEventType / MissingTemplateContext for poison-pill conditions --
    callers should catch these separately from transient (retryable) errors.
    """
    spec = EVENT_TEMPLATE_REGISTRY.get(event_type)
    if spec is None:
        raise UnknownEventType(event_type)

    missing = [f for f in spec.required_fields if f not in context]
    if missing:
        raise MissingTemplateContext(f"{event_type} missing fields: {missing}")

    subject = spec.subject_template.format(**context)

    body_path = os.path.join(_TEMPLATE_DIR, spec.body_file)
    with open(body_path, "r", encoding="utf-8") as f:
        body_template = f.read()
    body = body_template.format(**context)

    return subject, body
