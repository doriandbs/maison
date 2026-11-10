"""Entrées du menu principal et section active, fournies à tous les gabarits."""

from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Entree:
    section: str
    route: str
    libelle: str | Promise
    icone: str
    # Affichée dans la barre d'onglets du téléphone (les autres vont dans « Plus »).
    onglet: bool = False


ENTREES = (
    Entree("accueil", "accueil", _("Accueil"), "accueil", onglet=True),
    Entree("comptes", "banque:comptes", _("Comptes"), "comptes", onglet=True),
    Entree("operations", "banque:operations", _("Opérations"), "operations", onglet=True),
    Entree("budget", "budget:courant", _("Budget"), "budget", onglet=True),
    Entree("documents", "documents:liste", _("Documents"), "documents"),
    Entree("categories", "banque:categories", _("Catégories"), "categories"),
    Entree("membres", "foyers:membres", _("Membres"), "membres"),
)


def section_de(espace: str, nom: str) -> str:
    """Section du menu à laquelle appartient une route (`espace:nom`)."""
    if nom == "accueil":
        return "accueil"
    if espace == "banque":
        if "categorie" in nom or "regle" in nom:
            return "categories"
        if "operation" in nom or "virement" in nom or "import" in nom:
            return "operations"
        return "comptes"
    if espace == "foyers":
        return "membres" if nom in {"membres", "inviter", "changer_role"} else "foyers"
    return espace


def navigation(request: HttpRequest) -> dict[str, Any]:
    route = getattr(request, "resolver_match", None)
    section = section_de(route.namespace, route.url_name or "") if route else ""
    return {
        "section_courante": section,
        "navigation": [
            {
                "section": entree.section,
                "url": reverse(entree.route),
                "libelle": entree.libelle,
                "icone": entree.icone,
                "onglet": entree.onglet,
                "actif": entree.section == section,
            }
            for entree in ENTREES
        ],
    }
