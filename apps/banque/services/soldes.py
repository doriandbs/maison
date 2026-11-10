from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.banque.models import Compte, Operation, ReleveSolde
from apps.foyers.models import Foyer

ZERO = Decimal("0.00")


def soldes_des_comptes(foyer: Foyer, a_date: date | None = None) -> dict[int, Decimal]:
    """Solde de chaque compte du foyer, à la date donnée (aujourd'hui par défaut).

    - Compte suivi par opérations : solde initial + somme des opérations.
    - Compte valorisé (PEA, assurance vie…) : dernier relevé, augmenté des opérations
      postérieures à ce relevé ; sans relevé, il se comporte comme un compte ordinaire.
    """
    operations = Operation.objects.du_foyer(foyer)
    releves = ReleveSolde.objects.du_foyer(foyer)
    if a_date is not None:
        operations = operations.filter(date__lte=a_date)
        releves = releves.filter(date__lte=a_date)

    # order_by() vide : sans lui le tri par défaut du modèle s'ajouterait au GROUP BY.
    totaux: dict[int, Decimal] = dict(
        operations.order_by().values_list("compte_id").annotate(Sum("montant"))
    )
    dernier_releve: dict[int, ReleveSolde] = {
        releve.compte_id: releve for releve in releves.order_by("date")
    }

    soldes: dict[int, Decimal] = {}
    for compte in Compte.objects.du_foyer(foyer):
        releve = dernier_releve.get(compte.pk) if compte.est_valorise else None
        if releve is None:
            soldes[compte.pk] = compte.solde_initial + totaux.get(compte.pk, ZERO)
            continue
        depuis_le_releve = operations.filter(compte=compte, date__gt=releve.date).aggregate(
            total=Sum("montant")
        )["total"]
        soldes[compte.pk] = releve.montant + (depuis_le_releve or ZERO)
    return soldes


def enregistrer_releve(*, compte: Compte, date_releve: date, montant: Decimal) -> ReleveSolde:
    """Un seul relevé par compte et par jour : ressaisir une date corrige le relevé."""
    releve, _creation = ReleveSolde.objects.update_or_create(
        compte=compte, date=date_releve, defaults={"montant": montant, "foyer": compte.foyer}
    )
    return releve
