from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cached_property

from django.db.models import F
from django.utils.translation import gettext as _

from apps.banque.models import Compte, Operation
from apps.banque.services.soldes import soldes_des_comptes
from apps.budget.services.tableau import LigneCategorie, TableauMensuel, tableau_mensuel
from apps.documents.models import Document
from apps.foyers.models import Foyer

ZERO = Decimal("0.00")
NOMBRE_FACTURES = 5
NOMBRE_OPERATIONS = 5
# Au-delà, les plus petites catégories sont regroupées : l'œil ne distingue pas plus de couleurs.
NOMBRE_SERIES = 5


@dataclass
class PartDepense:
    libelle: str
    montant: Decimal
    pourcentage: Decimal
    debut: Decimal
    serie: int

    @property
    def fin(self) -> Decimal:
        return self.debut + self.pourcentage


def repartition_depenses(mois: TableauMensuel) -> list[PartDepense]:
    """Dépenses du mois par catégorie parente, de la plus grosse à la plus petite,
    avec leur position cumulée (en %) pour dessiner un anneau."""
    montants = [
        (ligne.categorie.nom, ligne.realise) for ligne in mois.depenses if ligne.realise > 0
    ]
    montants.sort(key=lambda paire: paire[1], reverse=True)
    if len(montants) > NOMBRE_SERIES:
        reste = sum((montant for _, montant in montants[NOMBRE_SERIES - 1 :]), ZERO)
        montants = [*montants[: NOMBRE_SERIES - 1], (_("Autres"), reste)]
    if mois.depenses_non_classees > 0:
        montants.append((_("À classer"), mois.depenses_non_classees))
    total = sum((montant for _, montant in montants), ZERO)
    if not total:
        return []
    parts, cumul = [], Decimal(0)
    for rang, (libelle, montant) in enumerate(montants):
        pourcentage = (montant / total * 100).quantize(Decimal("0.1"))
        parts.append(PartDepense(libelle, montant, pourcentage, cumul, serie=min(rang, 5) + 1))
        cumul += pourcentage
    # Le dernier arc ferme le cercle malgré les arrondis.
    parts[-1].pourcentage = Decimal(100) - parts[-1].debut
    return parts


@dataclass
class SoldeCompte:
    compte: Compte
    solde: Decimal


@dataclass
class FactureAPayer:
    document: Document
    en_retard: bool


@dataclass
class Synthese:
    aujourd_hui: date
    comptes: list[SoldeCompte]
    mois: TableauMensuel
    factures: list[FactureAPayer]
    nombre_factures: int
    montant_factures: Decimal
    dernieres_operations: list[Operation]

    @property
    def disponible(self) -> Decimal:
        """Argent des comptes courants, hors épargne et placements."""
        return sum((ligne.solde for ligne in self.comptes if not ligne.compte.est_epargne), ZERO)

    @property
    def epargne(self) -> Decimal:
        return sum((ligne.solde for ligne in self.comptes if ligne.compte.est_epargne), ZERO)

    @property
    def budget_restant(self) -> Decimal | None:
        """Budget de dépenses du mois moins ce qui est déjà dépensé ; None sans budget."""
        if not self.mois.budget_total:
            return None
        return self.mois.budget_total - self.mois.flux.depenses

    @property
    def patrimoine(self) -> Decimal:
        return self.disponible + self.epargne

    @property
    def alertes(self) -> list[LigneCategorie]:
        return self.mois.alertes

    @cached_property
    def repartition(self) -> list[PartDepense]:
        return repartition_depenses(self.mois)

    @property
    def degrade_repartition(self) -> str:
        """Valeur CSS `conic-gradient(...)` de l'anneau des dépenses."""
        arcs = ", ".join(
            f"var(--serie-{part.serie}) {part.debut}% {part.fin}%" for part in self.repartition
        )
        return f"conic-gradient({arcs})"


def synthese(foyer: Foyer, aujourd_hui: date | None = None) -> Synthese:
    aujourd_hui = aujourd_hui or date.today()
    soldes = soldes_des_comptes(foyer, aujourd_hui)
    comptes = [
        SoldeCompte(compte, soldes[compte.pk]) for compte in Compte.objects.du_foyer(foyer).actifs()
    ]

    a_payer = Document.objects.du_foyer(foyer).a_payer()
    # Les plus urgentes d'abord ; une facture sans échéance passe après les autres.
    factures = a_payer.order_by(F("echeance").asc(nulls_last=True), "date")[:NOMBRE_FACTURES]
    montant_factures = sum((d.montant or ZERO for d in a_payer.only("montant")), ZERO)

    return Synthese(
        aujourd_hui=aujourd_hui,
        comptes=comptes,
        mois=tableau_mensuel(foyer, aujourd_hui.year, aujourd_hui.month),
        factures=[
            FactureAPayer(d, en_retard=d.echeance is not None and d.echeance < aujourd_hui)
            for d in factures
        ],
        nombre_factures=a_payer.count(),
        montant_factures=montant_factures,
        dernieres_operations=list(
            Operation.objects.du_foyer(foyer)
            .filter(date__lte=aujourd_hui)
            .select_related("compte", "categorie__parent")[:NOMBRE_OPERATIONS]
        ),
    )
