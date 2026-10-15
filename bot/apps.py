from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _create_admin_defaults(sender, **kwargs):
    from .services import ensure_admin_defaults

    ensure_admin_defaults()


class BotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bot'
    verbose_name = 'Бот'

    def ready(self):
        post_migrate.connect(_create_admin_defaults, sender=self)
