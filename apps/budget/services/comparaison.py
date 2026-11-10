"""Comparaison mois par mois d'une année avec la précédente, en histogramme."""

from __future__ import annotations

from datetime import date

from django.utils import formats

from apps.budget.services.recap import RecapAnnuel
from apps.socle.graphiques import Histogramme, histogramme_groupe

MESURES = ("depenses", "revenus")


def histogramme_annuel(
    recap: RecapAnnuel, precedent: RecapAnnuel, mesure: str, aujourd_hui: date
) -> Histogramme | None:
    """Barres de l'année et de la précédente ; les mois pas encore commencés restent vides."""
    categories = [
        (formats.date_format(mois, "F Y").capitalize(), formats.date_format(mois, "M"))
        for mois in recap.mois
    ]
    annee = [
        getattr(flux, mesure) if mois <= aujourd_hui else None
        for mois, flux in zip(recap.mois, recap.flux_par_mois, strict=True)
    ]
    avant = [getattr(flux, mesure) for flux in precedent.flux_par_mois]
    return histogramme_groupe(
        categories, annee, avant, noms=(str(recap.annee), str(precedent.annee))
    )
