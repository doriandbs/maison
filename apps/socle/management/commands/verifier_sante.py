from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.socle.sante import base_joignable, migrations_en_attente


class Command(BaseCommand):
    help = "Vérifie que la base répond et que toutes les migrations sont appliquées."

    def handle(self, *args: Any, **options: Any) -> None:
        if not base_joignable():
            raise CommandError("Base de données injoignable.")
        en_attente = migrations_en_attente()
        if en_attente:
            raise CommandError(f"Migrations non appliquées : {', '.join(en_attente)}")
        self.stdout.write(self.style.SUCCESS("ok"))
