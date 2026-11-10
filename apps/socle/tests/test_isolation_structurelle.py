"""Garde-fous génériques : ils échouent dès qu'un nouveau modèle ou une nouvelle URL
oublie le rattachement au foyer ou le contrôle d'accès."""

from collections.abc import Iterator

import pytest
from django.apps import apps
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.urls.converters import IntConverter

from apps.foyers.models import Foyer
from apps.socle.models import ModeleDeFoyer, RequeteDeFoyer
from apps.utilisateurs.models import Utilisateur

MODELES_HORS_FOYER = {Utilisateur, Foyer}

URLS_PUBLIQUES = {
    "sante",
    "utilisateurs:inscription",
    "utilisateurs:inscription_envoyee",
    "utilisateurs:activation",
    "utilisateurs:connexion",
    "utilisateurs:deconnexion",
    "utilisateurs:mot_de_passe_oublie",
    "utilisateurs:mot_de_passe_envoye",
    "utilisateurs:mot_de_passe_nouveau",
    "utilisateurs:mot_de_passe_termine",
}


def _modeles_du_projet() -> list[type]:
    return [m for m in apps.get_models() if m.__module__.startswith("apps.")]


def test_tout_modele_metier_est_rattache_a_un_foyer():
    fautifs = [
        m
        for m in _modeles_du_projet()
        if m not in MODELES_HORS_FOYER and not issubclass(m, ModeleDeFoyer)
    ]
    assert fautifs == []


def test_le_gestionnaire_par_defaut_sait_filtrer_par_foyer():
    fautifs = [
        m
        for m in _modeles_du_projet()
        if issubclass(m, ModeleDeFoyer) and not isinstance(m._default_manager.all(), RequeteDeFoyer)
    ]
    assert fautifs == []


def _routes(resolveur: URLResolver, espace: str = "") -> Iterator[tuple[str, dict]]:
    for motif in resolveur.url_patterns:
        if isinstance(motif, URLResolver):
            if motif.namespace == "admin":
                continue
            prefixe = f"{espace}{motif.namespace}:" if motif.namespace else espace
            yield from _routes(motif, prefixe)
        elif isinstance(motif, URLPattern) and motif.name:
            arguments = {
                nom: 1 if isinstance(convertisseur, IntConverter) else "x"
                for nom, convertisseur in motif.pattern.converters.items()
            }
            yield f"{espace}{motif.name}", arguments


ROUTES_PROTEGEES = [
    (nom, arguments) for nom, arguments in _routes(get_resolver()) if nom not in URLS_PUBLIQUES
]


def test_des_routes_protegees_existent():
    assert len(ROUTES_PROTEGEES) >= 10


@pytest.mark.django_db
@pytest.mark.parametrize("methode", ["get", "post"])
@pytest.mark.parametrize(("nom", "arguments"), ROUTES_PROTEGEES)
def test_un_anonyme_est_renvoye_a_la_connexion(client, nom, arguments, methode):
    reponse = getattr(client, methode)(reverse(nom, kwargs=arguments))

    assert reponse.status_code == 302
    assert reponse["Location"].startswith(reverse("utilisateurs:connexion"))
