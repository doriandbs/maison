"""Crédits d'un foyer à une date : capital restant dû, biens financés, tableau par année."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import groupby

from apps.foyers.models import Foyer
from apps.prets.models import Pret

from .amortissement import ZERO, Echeance, Tableau, ajouter_mois


@dataclass
class Encours:
    pret: Pret
    tableau: Tableau
    a_date: date

    @property
    def capital_restant_du(self) -> Decimal:
        return self.tableau.capital_restant_du(self.a_date)

    @property
    def part_remboursee(self) -> Decimal:
        """En %, de 0 à 100 (le capital dû dépasse l'emprunt pendant un différé total)."""
        rembourse = self.pret.capital - self.capital_restant_du
        return min(max(rembourse / self.pret.capital * 100, Decimal(0)), Decimal(100))

    @property
    def est_termine(self) -> bool:
        return self.capital_restant_du == 0

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
    prets = Pret.objects.du_foyer(foyer).prefetch_related("remboursements")
    return [Encours(pret, pret.tableau(), a_date) for pret in prets]


def total_dettes(encours: Iterable[Encours]) -> Decimal:
    return sum((e.capital_restant_du for e in encours), ZERO)


def total_biens(encours: Iterable[Encours]) -> Decimal:
    """Valeur des biens financés, comptée à partir du mois qui précède la 1re échéance."""
    return sum(
        (
            e.pret.valeur_bien
            for e in encours
            if e.pret.valeur_bien and e.a_date >= ajouter_mois(e.pret.premiere_echeance, -1)
        ),
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
