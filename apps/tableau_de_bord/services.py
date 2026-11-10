from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import F

from apps.banque.models import Compte, Operation
from apps.banque.services.soldes import soldes_des_comptes
from apps.budget.services.tableau import LigneCategorie, TableauMensuel, tableau_mensuel
from apps.documents.models import Document
from apps.foyers.models import Foyer

ZERO = Decimal("0.00")
NOMBRE_FACTURES = 5
NOMBRE_OPERATIONS = 5


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
    def alertes(self) -> list[LigneCategorie]:
        return self.mois.alertes


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
