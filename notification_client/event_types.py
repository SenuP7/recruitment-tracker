"""Event type constants shared between Django publishers and the Lambda consumer's
template registry (notification-service/lambda/notifier/templates.py). Keep the two
in sync when adding a new trigger.
"""

APPLICATION_STATUS_CHANGED = "application_status_changed"
INTERVIEW_SCHEDULED = "interview_scheduled"
INTERVIEW_UPDATED = "interview_updated"
INTERVIEW_CANCELLED = "interview_cancelled"
APPLICATION_CONFIRM = "application_confirm"
PORTAL_INVITE = "portal_invite"
STAFF_INVITE = "staff_invite"
PASSWORD_RESET = "password_reset"
