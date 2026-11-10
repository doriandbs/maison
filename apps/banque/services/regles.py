"""Catégorisation automatique : « le libellé contient <motif> » → sous-catégorie."""

from __future__ import annotations

import unicodedata

from django.db import transaction

from apps.banque.models import Categorie, Operation, RegleCategorisation
from apps.foyers.models import Foyer


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, espaces réduits : « Échéance  PRÊT » → « echeance pret »."""
    decompose = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return " ".join(sans_accents.casefold().split())


class Classeur:
    """Règles d'un foyer chargées une fois, appliquées à autant d'opérations que voulu."""

    def __init__(self, foyer: Foyer) -> None:
        regles = RegleCategorisation.objects.du_foyer(foyer).select_related("categorie")
        # Le motif le plus long (le plus précis) l'emporte : « UBER EATS » avant « UBER ».
        self.regles = sorted(
            ((normaliser(regle.motif), regle.categorie) for regle in regles if regle.motif),
            key=lambda paire: len(paire[0]),
            reverse=True,
        )

    def categorie(self, *textes: str) -> Categorie | None:
        cible = normaliser(" ".join(textes))
        for motif, categorie in self.regles:
            if motif in cible and categorie.archive_le is None:
                return categorie
        return None


@transaction.atomic
def memoriser(foyer: Foyer, motif: str, categorie: Categorie) -> RegleCategorisation:
    """Crée la règle, ou la redirige vers la nouvelle catégorie si le motif existe déjà."""
    motif = " ".join(motif.split())[:100]
    existante = next(
        (
            regle
            for regle in RegleCategorisation.objects.du_foyer(foyer)
            if normaliser(regle.motif) == normaliser(motif)
        ),
        None,
    )
    if existante is not None:
        existante.categorie = categorie
        existante.save(update_fields=["categorie", "modifie_le"])
        return existante
    return RegleCategorisation.objects.create(foyer=foyer, motif=motif, categorie=categorie)


@transaction.atomic
def appliquer_aux_operations_a_classer(foyer: Foyer) -> int:
    """Classe les opérations sans catégorie (hors virements internes) ; renvoie leur nombre."""
    classeur = Classeur(foyer)
    a_classer = Operation.objects.du_foyer(foyer).filter(
        categorie__isnull=True, groupe_virement__isnull=True
    )
    classees = []
    for operation in a_classer:
        categorie = classeur.categorie(operation.libelle, operation.libelle_banque)
        if categorie is not None:
            operation.categorie = categorie
            classees.append(operation)
    Operation.objects.bulk_update(classees, ["categorie"])
    return len(classees)
