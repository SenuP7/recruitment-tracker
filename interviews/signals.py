from django.db import transaction
from django.db.models.signals import post_save, pre_save
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


@receiver(pre_save, sender=Interview)
def _stash_previous(sender, instance, **kwargs):
    """Reads (never writes) the stored row so post_save can tell what changed
    without an extra column."""
    if not instance.pk:
        instance._previous = None
        return
    try:
        instance._previous = Interview.objects.only("scheduled_date", "status").get(pk=instance.pk)
    except Interview.DoesNotExist:
        instance._previous = None


@receiver(post_save, sender=Interview)
def _notify_on_change(sender, instance, created, **kwargs):
    """Tells the candidate when a round moves or is cancelled.

    Until this existed they were only emailed when an interview was created,
    so a rescheduled interview left them turning up at the old time.
    """
    if created:
        return

    previous = getattr(instance, "_previous", None)
    if previous is None:
        return

    application = instance.application
    candidate = application.candidate
    candidate_name = f"{candidate.first_name} {candidate.last_name}"
    base = {
        "candidate_name": candidate_name,
        "job_title": application.position.title,
        "interview_type": instance.interview_type,
    }

    if previous.status != "Cancelled" and instance.status == "Cancelled":
        def _publish_cancelled():
            publish_event(
                event_types.INTERVIEW_CANCELLED,
                recipient_email=candidate.email,
                recipient_name=candidate_name,
                context={**base, "scheduled_date": instance.scheduled_date.isoformat()},
            )

        transaction.on_commit(_publish_cancelled)
        return

    if previous.scheduled_date != instance.scheduled_date and instance.status == "Scheduled":
        location_line = f"Where: {instance.location}\n" if instance.location else ""
        if instance.meeting_link:
            location_line += f"Join: {instance.meeting_link}\n"

        def _publish_moved():
            publish_event(
                event_types.INTERVIEW_UPDATED,
                recipient_email=candidate.email,
                recipient_name=candidate_name,
                context={
                    **base,
                    "scheduled_date": instance.scheduled_date.isoformat(),
                    "location_line": location_line,
                },
            )

        transaction.on_commit(_publish_moved)
