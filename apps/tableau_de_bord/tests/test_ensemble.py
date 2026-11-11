from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.banque.tests.fabriques import FabriqueCompte, FabriqueOperation
from apps.documents.tests.fabriques import FabriqueDocument
from apps.foyers.models import Role
from apps.foyers.tests.fabriques import FabriqueAdhesion, acces_a, espace_de
from apps.prets.tests.fabriques import FabriquePret
from apps.tableau_de_bord import patrimoine
from apps.tableau_de_bord.ensemble import additionner

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def medias(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def couple(client):
    """Dorian et Alexandra partagent « Maison » ; Alexandra est connectée."""
    dorian = espace_de()
    alexandra = acces_a(dorian, Role.MEMBRE)
    FabriqueCompte(
        foyer=dorian.foyer, nom="SG Dorian", solde_initial=D("1000"), ouvert_le=date(2024, 1, 1)
    )
    espace_alexandra = espace_de(alexandra.utilisateur)
    FabriqueCompte(
        foyer=espace_alexandra.foyer,
        nom="Bourso Alexandra",
        solde_initial=D("500"),
        ouvert_le=date(2024, 1, 1),
    )
    FabriquePret(
        foyer=dorian.foyer, capital=D("200"), duree_mois=12, premiere_echeance=date(2030, 1, 1)
    )
    client.force_login(alexandra.utilisateur)
    return dorian, alexandra


def test_reunit_les_finances_de_tous_les_membres(client, couple):
    dorian, alexandra = couple
    FabriqueOperation(compte=FabriqueCompte(foyer=dorian.foyer), libelle="Courses Dorian")
    FabriqueDocument(foyer=alexandra.foyer, titre="Facture d'eau", montant=D("40"))
    FabriqueCompte(foyer=espace_de().foyer, nom="Compte d'un inconnu", solde_initial=D("99999"))

    reponse = client.get(reverse("ensemble"))
    contenu = reponse.content.decode()
    ensemble = reponse.context["ensemble"]

    assert ensemble.patrimoine_net == D("1490")  # 1 000 + 500 − 10 de courses
    assert len(ensemble.membres) == 2
    assert "Courses Dorian" in contenu and "Facture d" in contenu
    assert "inconnu" not in contenu
    assert ensemble.courbe is not None


def test_reserve_a_un_foyer_partage(client):
    client.force_login(espace_de().utilisateur)

    assert client.get(reverse("ensemble")).url == reverse("foyers:liste")


def test_un_lecteur_voit_l_ensemble(client):
    dorian = espace_de()
    lecteur = acces_a(dorian, Role.LECTEUR)
    client.force_login(lecteur.utilisateur)

    assert client.get(reverse("ensemble")).status_code == 200


def test_ne_suit_pas_un_autre_foyer_de_l_utilisateur(client, couple):
    dorian, alexandra = couple
    parents = FabriqueAdhesion(utilisateur=alexandra.utilisateur, est_principal=False)
    FabriqueCompte(
        foyer=espace_de(FabriqueAdhesion(foyer=parents.foyer).utilisateur).foyer,
        nom="Compte de la mère",
    )

    contenu = client.get(reverse("ensemble")).content.decode()

    assert "mère" not in contenu


def test_additionner_les_courbes():
    jour = date(2026, 1, 31)
    a = [
        patrimoine.PointPatrimoine(jour, D("10"), False),
        patrimoine.PointPatrimoine(date(2026, 2, 5), D("12"), True),
    ]
    b = [patrimoine.PointPatrimoine(date(2026, 2, 5), D("3"), True)]

    total = additionner([a, b])

    assert [(p.date, p.valeur, p.en_cours) for p in total] == [
        (jour, D("10"), False),
        (date(2026, 2, 5), D("15"), True),
    ]
