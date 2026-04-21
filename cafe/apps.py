from django.apps import AppConfig


class CafeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cafe'

    def ready(self):
        # noqa: F401 — register signals
        from . import signals  # pylint: disable=unused-import

