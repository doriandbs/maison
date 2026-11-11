"""Vue « Ensemble » d'un foyer : les finances de tous ses membres réunies, en lecture."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.banque.models import Operation
from apps.foyers.models import Adhesion, Foyer
from apps.socle.graphiques import Courbe

from . import patrimoine
from .services import ZERO, FactureAPayer, Synthese, factures_a_payer, synthese


@dataclass
class FinancesDe:
    acces: Adhesion
    synthese: Synthese

    @property
    def personne(self) -> object:
        return self.acces.foyer.personne


@dataclass
class Ensemble:
    aujourd_hui: date
    membres: list[FinancesDe]
    courbe: Courbe | None
    points: list[patrimoine.PointPatrimoine]
    dernieres_operations: list[Operation]
    factures: list[FactureAPayer]
    nombre_factures: int
    montant_factures: Decimal

    @property
    def patrimoine_net(self) -> Decimal:
        return sum((m.synthese.patrimoine_net for m in self.membres), ZERO)

    @property
    def disponible(self) -> Decimal:
        return sum((m.synthese.disponible for m in self.membres), ZERO)

    @property
    def epargne(self) -> Decimal:
        return sum((m.synthese.epargne for m in self.membres), ZERO)

    @property
    def dettes(self) -> Decimal:
        return sum((m.synthese.dettes for m in self.membres), ZERO)

    @property
    def biens(self) -> Decimal:
        return sum((m.synthese.biens for m in self.membres), ZERO)

    @property
    def depenses_du_mois(self) -> Decimal:
        return sum((m.synthese.mois.flux.depenses for m in self.membres), ZERO)

    @property
    def revenus_du_mois(self) -> Decimal:
        return sum((m.synthese.mois.flux.revenus for m in self.membres), ZERO)


def additionner(series: list[list[patrimoine.PointPatrimoine]]) -> list[patrimoine.PointPatrimoine]:
    """Somme date par date ; une personne n'y entre qu'à partir de ses premiers comptes."""
    totaux: dict[date, Decimal] = defaultdict(lambda: ZERO)
    en_cours: dict[date, bool] = {}
    for serie in series:
        for point in serie:
            totaux[point.date] += point.valeur
            en_cours[point.date] = point.en_cours
    return [
        patrimoine.PointPatrimoine(jour, totaux[jour], en_cours[jour]) for jour in sorted(totaux)
    ]


def ensemble(
    acces: list[Adhesion], foyer: Foyer, mois: int, aujourd_hui: date | None = None
) -> Ensemble:
    aujourd_hui = aujourd_hui or date.today()
    membres = [FinancesDe(a, synthese(a.foyer, aujourd_hui)) for a in acces]
    points = additionner([patrimoine.evolution(a.foyer, mois, aujourd_hui) for a in acces])
    espaces = [a.foyer for a in acces]
    factures, nombre, montant = factures_a_payer(foyer, aujourd_hui)
    return Ensemble(
        aujourd_hui=aujourd_hui,
        membres=membres,
        courbe=patrimoine.graphique(points),
        points=points,
        dernieres_operations=list(
            Operation.objects.filter(foyer__in=espaces, date__lte=aujourd_hui)
            .select_related("compte", "foyer__personne")
            .order_by("-date", "-id")[:10]
        ),
        factures=factures,
        nombre_factures=nombre,
        montant_factures=montant,
    )
