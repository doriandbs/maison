from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.utilisateurs import double_auth
from apps.utilisateurs.models import Utilisateur


class Command(BaseCommand):
    help = (
        "Retire la double authentification d'un compte (téléphone ET codes de secours perdus). "
        "La personne devra la reconfigurer à sa prochaine connexion."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("email")

    def handle(self, *args: Any, email: str, **options: Any) -> None:
        utilisateur = Utilisateur.objects.filter(email=email.strip().lower()).first()
        if utilisateur is None:
            raise CommandError(f"Aucun compte pour {email}.")
        double_auth.retirer(utilisateur)
        self.stdout.write(
            self.style.SUCCESS(
                f"Double authentification retirée pour {utilisateur.email}. "
                "Vérifiez son identité avant de lui confirmer qu'elle peut se reconnecter."
            )
        )
