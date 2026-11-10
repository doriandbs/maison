from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.banque.models import Categorie, Nature
from apps.budget.models import LigneBudget
from apps.foyers.models import Foyer

from .flux import ZERO


def budgets_du_mois(foyer: Foyer, mois: date) -> dict[int, Decimal]:
    """Budget saisi applicable à chaque catégorie pour ce mois (absente = pas de budget).

    La dernière ligne ordinaire antérieure ou égale au mois s'applique, sauf si une
    ligne ponctuelle existe pour ce mois précis.
    """
    lignes = LigneBudget.objects.du_foyer(foyer).filter(mois__lte=mois).order_by("mois")
    budgets: dict[int, Decimal] = {}
    ponctuels: dict[int, Decimal] = {}
    for ligne in lignes:
        if not ligne.ponctuel:
            budgets[ligne.categorie_id] = ligne.montant
        elif ligne.mois == mois:
            ponctuels[ligne.categorie_id] = ligne.montant
    budgets.update(ponctuels)
    return {categorie_id: montant for categorie_id, montant in budgets.items() if montant > 0}


@transaction.atomic
def enregistrer_budgets(
    *, foyer: Foyer, mois: date, montants: dict[int, Decimal | None], ponctuel: bool
) -> int:
    """Enregistre les budgets modifiés et renvoie leur nombre.

    `ponctuel=False` : la valeur vaut à partir de ce mois ; une éventuelle surcharge
    ponctuelle de ce même mois est retirée pour que la nouvelle valeur s'applique.
    Seules les catégories de dépense du foyer sont acceptées ; les autres identifiants
    sont ignorés.
    """
    actuels = budgets_du_mois(foyer, mois)
    autorisees = set(
        Categorie.objects.du_foyer(foyer).filter(nature=Nature.DEPENSE).values_list("pk", flat=True)
    )
    modifies = 0
    for categorie_id, montant in montants.items():
        montant = montant or ZERO
        if categorie_id not in autorisees or montant == actuels.get(categorie_id, ZERO):
            continue
        LigneBudget.objects.update_or_create(
            foyer=foyer,
            categorie_id=categorie_id,
            mois=mois,
            ponctuel=ponctuel,
            defaults={"montant": montant},
        )
        if not ponctuel:
            LigneBudget.objects.du_foyer(foyer).filter(
                categorie_id=categorie_id, mois=mois, ponctuel=True
            ).delete()
        modifies += 1
    return modifies
