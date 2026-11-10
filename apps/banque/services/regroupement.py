from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.utils.translation import gettext as _

from apps.banque.models import Compte

ZERO = Decimal("0.00")


@dataclass
class LigneCompte:
    compte: Compte
    solde: Decimal


@dataclass
class GroupeEtablissement:
    nom: str
    lignes: list[LigneCompte] = field(default_factory=list)
    est_sans_etablissement: bool = False

    @property
    def total(self) -> Decimal:
        return sum((ligne.solde for ligne in self.lignes), ZERO)


def _cle(etablissement: str) -> str:
    """« Banque Populaire », « banque  populaire » et « BANQUE POPULAIRE » vont ensemble."""
    return " ".join(etablissement.split()).casefold()


def _nom_retenu(graphies: list[str]) -> str:
    """La graphie la plus fréquente ; à égalité, celle qui a le plus de majuscules
    (« Boursorama » plutôt que « boursorama »)."""
    return max(graphies, key=lambda nom: (graphies.count(nom), sum(c.isupper() for c in nom)))


def regrouper_par_etablissement(
    comptes: list[Compte], soldes: dict[int, Decimal]
) -> list[GroupeEtablissement]:
    """Comptes réunis par établissement, par ordre alphabétique ; ceux sans établissement
    en dernier."""
    groupes: dict[str, GroupeEtablissement] = {}
    graphies: dict[str, list[str]] = {}
    for compte in comptes:
        nom = " ".join(compte.etablissement.split())
        cle = nom.casefold()
        groupe = groupes.setdefault(cle, GroupeEtablissement(nom, est_sans_etablissement=not cle))
        groupe.lignes.append(LigneCompte(compte, soldes[compte.pk]))
        graphies.setdefault(cle, []).append(nom)
    for cle, groupe in groupes.items():
        groupe.nom = _nom_retenu(graphies[cle]) if cle else _("Sans établissement")
    return sorted(groupes.values(), key=lambda g: (g.est_sans_etablissement, _cle(g.nom)))
