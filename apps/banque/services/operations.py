import uuid
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.banque.models import Compte, Operation
from apps.foyers.models import Foyer
from apps.utilisateurs.models import Utilisateur


class ErreurVirement(ValueError):
    pass


@transaction.atomic
def creer_virement(
    *,
    source: Compte,
    destination: Compte,
    date_virement: date,
    montant: Decimal,
    libelle: str,
    cree_par: Utilisateur | None = None,
) -> tuple[Operation, Operation]:
    """Crée les deux opérations liées d'un virement interne (débit puis crédit)."""
    if source.pk == destination.pk:
        raise ErreurVirement("Les comptes source et destination doivent être différents.")
    if not _meme_foyer(source, destination):
        raise ErreurVirement("Un virement interne reste dans un même foyer.")
    if montant <= 0:
        raise ErreurVirement("Le montant d'un virement est strictement positif.")
    communs = {
        "date": date_virement,
        "libelle": libelle,
        "groupe_virement": uuid.uuid4(),
        "cree_par": cree_par,
    }
    # Chaque opération reste dans l'espace de son compte (Dorian → Alexandra, par exemple).
    debit = Operation.objects.create(compte=source, foyer=source.foyer, montant=-montant, **communs)
    credit = Operation.objects.create(
        compte=destination, foyer=destination.foyer, montant=montant, **communs
    )
    return debit, credit


def _meme_foyer(source: Compte, destination: Compte) -> bool:
    """Même espace, ou espaces de deux personnes qui partagent un foyer."""
    if source.foyer_id == destination.foyer_id:
        return True
    titulaires = {source.foyer.personne_id, destination.foyer.personne_id}
    if None in titulaires:
        return False
    return (
        Foyer.objects.filter(personne__isnull=True, adhesions__utilisateur=source.foyer.personne_id)
        .filter(adhesions__utilisateur=destination.foyer.personne_id)
        .exists()
    )


@transaction.atomic
def supprimer_operation(operation: Operation) -> None:
    """Supprimer une opération de virement supprime aussi sa contrepartie."""
    if operation.est_virement:
        Operation.objects.filter(groupe_virement=operation.groupe_virement).delete()
    else:
        operation.delete()
