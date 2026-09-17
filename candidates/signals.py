from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from notification_client import event_types
from notification_client.publisher import publish_event

from .models import Application


@receiver(pre_save, sender=Application)
def _stash_old_status(sender, instance, **kwargs):
    """Reads (never writes) the current DB status so post_save can detect a
    transition without an extra column or write."""
    if instance.pk:
        try:
            instance._old_status = Application.objects.only("status").get(pk=instance.pk).status
        except Application.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender=Application)
def _notify_on_status_change(sender, instance, created, **kwargs):
    if created:
        return  # the initial "Applied" row isn't a transition

    old_status = getattr(instance, "_old_status", None)
    if old_status is None or old_status == instance.status:
        return

    candidate = instance.candidate
    position = instance.position
    candidate_name = f"{candidate.first_name} {candidate.last_name}"

    def _publish():
        publish_event(
            event_types.APPLICATION_STATUS_CHANGED,
            recipient_email=candidate.email,
            recipient_name=candidate_name,
            context={
                "candidate_name": candidate_name,
                "job_title": position.title,
                "old_status": old_status,
                "new_status": instance.status,
                "application_id": instance.pk,
            },
        )

    # Only publish once the transaction actually commits -- a status change
    # inside an atomic block that later rolls back must never send an email.
    transaction.on_commit(_publish)
