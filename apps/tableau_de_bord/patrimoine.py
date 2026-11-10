"""Patrimoine net en fin de chaque mois, pour la courbe de l'accueil."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import formats
from django.utils.translation import gettext as _

from apps.banque.models import Compte
from apps.banque.services.soldes import soldes_des_comptes
from apps.foyers.models import Foyer
from apps.prets.services.amortissement import ajouter_mois
from apps.prets.services.encours import Encours, encours_du_foyer, total_biens, total_dettes
from apps.socle.graphiques import Courbe, courbe

PERIODES = (12, 24)
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class PointPatrimoine:
    date: date
    valeur: Decimal
    en_cours: bool  # le mois courant : valeur du jour, pas de fin de mois


def _fin_de_mois(jour: date) -> date:
    return ajouter_mois(jour.replace(day=1), 1) - timedelta(days=1)


def evolution(foyer: Foyer, mois: int, aujourd_hui: date) -> list[PointPatrimoine]:
    """Fins des `mois` derniers mois (aujourd'hui pour le mois en cours).

    Un compte ne compte qu'à partir de la date de son solde initial : avant, on ignore ce
    qu'il valait. La courbe commence donc au premier mois où un compte existe.
    """
    comptes = list(Compte.objects.du_foyer(foyer))
    if not comptes:
        return []
    debut = min(compte.ouvert_le for compte in comptes)
    credits = encours_du_foyer(foyer, aujourd_hui)

    points = []
    for recul in range(mois - 1, -1, -1):
        jour = aujourd_hui if recul == 0 else _fin_de_mois(ajouter_mois(aujourd_hui, -recul))
        if jour < debut:
            continue
        soldes = soldes_des_comptes(foyer, jour)
        avoirs = sum((soldes[c.pk] for c in comptes if c.ouvert_le <= jour), ZERO)
        a_date = [Encours(e.pret, e.tableau, jour) for e in credits]
        valeur = avoirs + total_biens(a_date) - total_dettes(a_date)
        points.append(PointPatrimoine(jour, valeur, en_cours=recul == 0))
    return points


def graphique(points: list[PointPatrimoine]) -> Courbe | None:
    return courbe(
        [
            (
                _("aujourd'hui") if p.en_cours else formats.date_format(p.date, "F Y").capitalize(),
                formats.date_format(p.date, "M y"),
                p.valeur,
            )
            for p in points
        ]
    )
