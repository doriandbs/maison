"""Briques communes au tableau mensuel et au récap annuel.

Règles de calcul :
- un virement interne n'est ni un revenu ni une dépense ;
- le réalisé d'une catégorie est net : un remboursement saisi en recette dans une
  catégorie de dépense vient en déduction de cette dépense ;
- une opération sans catégorie compte en revenu si elle est positive, en dépense sinon.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, Sum

from apps.banque.models import Categorie, Nature, Operation
from apps.banque.services.regles import normaliser
from apps.foyers.models import Foyer
from apps.socle.perimetre import Perimetre

ZERO = Decimal("0.00")

# (somme des montants positifs, somme des montants négatifs) d'un ensemble d'opérations.
Mouvement = tuple[Decimal, Decimal]
# Par catégorie ; la clé None regroupe les opérations sans catégorie.
MouvementsParCategorie = dict[int | None, Mouvement]


@dataclass(frozen=True)
class Flux:
    revenus: Decimal = ZERO
    depenses: Decimal = ZERO

    @property
    def epargne(self) -> Decimal:
        return self.revenus - self.depenses

    @property
    def taux_epargne(self) -> Decimal | None:
        """(revenus − dépenses) / revenus, en pourcentage ; indéfini sans revenu."""
        if self.revenus <= 0:
            return None
        return (self.epargne / self.revenus * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def premier_du_mois(annee: int, mois: int) -> date:
    return date(annee, mois, 1)


def dernier_du_mois(annee: int, mois: int) -> date:
    return date(annee, mois, monthrange(annee, mois)[1])


def mouvements_par_mois(
    foyer: Foyer | Perimetre, debut: date, fin: date
) -> dict[tuple[int, int], MouvementsParCategorie]:
    """Opérations hors virements, agrégées par (année, mois) puis par catégorie."""
    lignes = list(
        Operation.objects.du_foyer(foyer)
        .filter(date__range=(debut, fin), groupe_virement__isnull=True)
        .order_by()
        .values("date__year", "date__month", "categorie_id")
        .annotate(
            entrees=Sum("montant", filter=Q(montant__gt=0)),
            sorties=Sum("montant", filter=Q(montant__lt=0)),
        )
    )
    vers_classement = correspondance_des_categories(
        foyer, {ligne["categorie_id"] for ligne in lignes if ligne["categorie_id"]}
    )
    resultat: dict[tuple[int, int], MouvementsParCategorie] = {}
    for ligne in lignes:
        du_mois = resultat.setdefault((ligne["date__year"], ligne["date__month"]), {})
        cle = vers_classement.get(ligne["categorie_id"]) if ligne["categorie_id"] else None
        entrees, sorties = du_mois.get(cle, (ZERO, ZERO))
        du_mois[cle] = (entrees + (ligne["entrees"] or ZERO), sorties + (ligne["sorties"] or ZERO))
    return resultat


def correspondance_des_categories(foyer: Foyer | Perimetre, ids: set[int]) -> dict[int, int | None]:
    """Ramène chaque catégorie d'opération à celle du classement de même nom.

    Dans un foyer, chacun a pu classer ses opérations avec ses propres catégories (avant de
    rejoindre le foyer, ou depuis un autre foyer) : « Alimentation › Courses » d'une personne
    compte dans « Alimentation › Courses » du foyer. Sans équivalent : « à classer ».
    """
    classement = Categorie.objects.du_foyer(foyer).select_related("parent")
    connues = {c.pk for c in classement}
    inconnues = ids - connues
    resultat: dict[int, int | None] = {pk: pk for pk in ids & connues}
    if not inconnues:
        return resultat
    par_nom = {(normaliser(c.parent.nom), normaliser(c.nom)): c.pk for c in classement if c.parent}
    for categorie in Categorie.objects.filter(pk__in=inconnues).select_related("parent"):
        cle = (
            (normaliser(categorie.parent.nom), normaliser(categorie.nom))
            if categorie.parent
            else None
        )
        resultat[categorie.pk] = par_nom.get(cle) if cle else None
    return resultat


def montant_realise(nature: str, mouvement: Mouvement) -> Decimal:
    """Réalisé net d'une catégorie, positif dans le sens normal de sa nature."""
    net = mouvement[0] + mouvement[1]
    return net if nature == Nature.REVENU else -net


def calculer_flux(mouvements: MouvementsParCategorie, natures: dict[int, str]) -> Flux:
    revenus = depenses = ZERO
    for categorie_id, mouvement in mouvements.items():
        if categorie_id is None:
            revenus += mouvement[0]
            depenses -= mouvement[1]
        elif natures[categorie_id] == Nature.REVENU:
            revenus += montant_realise(Nature.REVENU, mouvement)
        else:
            depenses += montant_realise(Nature.DEPENSE, mouvement)
    return Flux(revenus=revenus, depenses=depenses)
