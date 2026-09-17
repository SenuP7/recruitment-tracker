from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from notification_client import event_types
from notification_client.publisher import publish_event

from .models import Interview


@receiver(post_save, sender=Interview)
def _notify_interview_scheduled(sender, instance, created, **kwargs):
    if not created:
        return

    application = instance.application
    candidate = application.candidate
    position = application.position
    candidate_name = f"{candidate.first_name} {candidate.last_name}"

    def _publish():
        publish_event(
            event_types.INTERVIEW_SCHEDULED,
            recipient_email=candidate.email,
            recipient_name=candidate_name,
            context={
                "candidate_name": candidate_name,
                "job_title": position.title,
                "interview_type": instance.interview_type,
                "scheduled_date": instance.scheduled_date.isoformat(),
                "interview_id": instance.pk,
            },
        )

    transaction.on_commit(_publish)
