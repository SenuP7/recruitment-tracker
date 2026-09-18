from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Registers the audit-log receivers for sign-in, sign-out and
        # failed sign-in.
        from . import signals  # noqa: F401
