import pytest

from notifier.templates import MissingTemplateContext, UnknownEventType, render


def test_render_application_status_changed():
    subject, body = render(
        "application_status_changed",
        {
            "candidate_name": "Jane Doe",
            "job_title": "Backend Engineer",
            "old_status": "CV Screening",
            "new_status": "HR Interview",
        },
    )
    assert subject == "Update on your application for Backend Engineer"
    assert "Jane Doe" in body
    assert "CV Screening" in body
    assert "HR Interview" in body


def test_render_interview_scheduled():
    subject, body = render(
        "interview_scheduled",
        {
            "candidate_name": "Jane Doe",
            "job_title": "Backend Engineer",
            "interview_type": "HR",
            "scheduled_date": "2026-09-15T14:30:00+00:00",
        },
    )
    assert "Interview Scheduled" in subject
    assert "HR" in body
    assert "2026-09-15T14:30:00+00:00" in body


def test_unknown_event_type_raises():
    with pytest.raises(UnknownEventType):
        render("not_a_real_event", {})


def test_missing_required_field_raises():
    with pytest.raises(MissingTemplateContext):
        render("application_status_changed", {"candidate_name": "Jane Doe"})
