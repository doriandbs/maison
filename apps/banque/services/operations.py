import uuid
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.banque.models import Compte, Operation
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
    if source.foyer_id != destination.foyer_id:
        raise ErreurVirement("Un virement interne reste dans un même foyer.")
    if montant <= 0:
        raise ErreurVirement("Le montant d'un virement est strictement positif.")
    communs = {
        "foyer": source.foyer,
        "date": date_virement,
        "libelle": libelle,
        "groupe_virement": uuid.uuid4(),
        "cree_par": cree_par,
    }
    debit = Operation.objects.create(compte=source, montant=-montant, **communs)
    credit = Operation.objects.create(compte=destination, montant=montant, **communs)
    return debit, credit


@transaction.atomic
def supprimer_operation(operation: Operation) -> None:
    """Supprimer une opération de virement supprime aussi sa contrepartie."""
    if operation.est_virement:
        Operation.objects.filter(
            foyer_id=operation.foyer_id, groupe_virement=operation.groupe_virement
        ).delete()
    else:
        operation.delete()
