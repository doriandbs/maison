"""Crédits d'un foyer à une date : capital restant dû, biens financés, tableau par année."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import groupby

from apps.foyers.models import Foyer
from apps.prets.models import Pret

from .amortissement import ZERO, Echeance, Tableau


@dataclass
class Encours:
    pret: Pret
    tableau: Tableau
    a_date: date

    @property
    def emprunteurs(self) -> int:
        return 1 + len(self.pret.co_emprunteurs.all())

    @property
    def part(self) -> Decimal:
        """Part de ce crédit portée par chacun : égale entre tous les emprunteurs."""
        return Decimal(1) / self.emprunteurs

    @property
    def a_commence(self) -> bool:
        """Le prêt (et le bien qu'il finance) n'existe qu'à partir de sa signature : avant,
        ni dette ni bien, sinon le patrimoine plongerait à tort (voir `Pret.debut`)."""
        return self.a_date >= self.pret.debut

    @property
    def capital_restant_du(self) -> Decimal:
        if not self.a_commence:
            return ZERO
        return self.tableau.capital_restant_du(self.a_date)

    @property
    def part_remboursee(self) -> Decimal:
        """En %, de 0 à 100 (le capital dû dépasse l'emprunt pendant un différé total)."""
        if not self.a_commence:
            return Decimal(0)
        rembourse = self.pret.capital - self.capital_restant_du
        return min(max(rembourse / self.pret.capital * 100, Decimal(0)), Decimal(100))

    @property
    def est_termine(self) -> bool:
        return self.a_commence and self.capital_restant_du == 0

    @property
    def prochaine_echeance(self) -> Echeance | None:
        return next((e for e in self.tableau.echeances if e.date > self.a_date), None)

    @property
    def echeances_restantes(self) -> int:
        return self.tableau.echeances_restantes(self.a_date)

    @property
    def interets_restants(self) -> Decimal:
        return sum((e.interets for e in self.tableau.echeances if e.date > self.a_date), ZERO)

    @property
    def en_differe(self) -> bool:
        prochaine = self.prochaine_echeance
        return prochaine is not None and prochaine.en_differe


def encours_du_foyer(foyer: Foyer, a_date: date) -> list[Encours]:
    """Crédits de cet espace, y compris ceux dont son titulaire est co-emprunteur."""
    prets = (
        Pret.objects.visibles_dans(foyer)
        .select_related("foyer__personne")
        .prefetch_related("remboursements", "co_emprunteurs")
    )
    return [Encours(pret, pret.tableau(), a_date) for pret in prets]


def _part(montant: Decimal, encours: Encours) -> Decimal:
    return (montant * encours.part).quantize(Decimal("0.01"))


def total_dettes(encours: Iterable[Encours]) -> Decimal:
    """Capital restant dû, chacun pour sa part : un crédit à deux compte pour moitié."""
    return sum((_part(e.capital_restant_du, e) for e in encours), ZERO)


def total_biens(encours: Iterable[Encours]) -> Decimal:
    """Valeur des biens financés, à partir du même moment que la dette (voir `a_commence`)."""
    return sum(
        (_part(e.pret.valeur_bien, e) for e in encours if e.pret.valeur_bien and e.a_commence),
        ZERO,
    )


@dataclass
class AnneeDuTableau:
    annee: int
    echeances: list[Echeance]
    en_cours: bool

    @property
    def interets(self) -> Decimal:
        return sum((e.interets for e in self.echeances), ZERO)

    @property
    def amortissement(self) -> Decimal:
        return sum((e.amortissement for e in self.echeances), ZERO)

    @property
    def assurance(self) -> Decimal:
        return sum((e.assurance for e in self.echeances), ZERO)

    @property
    def anticipe(self) -> Decimal:
        return sum((e.anticipe for e in self.echeances), ZERO)

    @property
    def capital_fin(self) -> Decimal:
        return self.echeances[-1].capital_fin


def par_annee(tableau: Tableau, aujourd_hui: date) -> list[AnneeDuTableau]:
    return [
        AnneeDuTableau(annee, list(echeances), en_cours=annee == aujourd_hui.year)
        for annee, echeances in groupby(tableau.echeances, key=lambda e: e.date.year)
    ]
