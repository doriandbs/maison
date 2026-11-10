from django.apps import AppConfig


class BanqueConfig(AppConfig):
    name = "apps.banque"
    label = "banque"
    verbose_name = "Banque"

    def ready(self) -> None:
        from . import recepteurs  # noqa: F401
