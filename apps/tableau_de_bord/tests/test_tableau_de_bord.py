from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.banque.models import TypeCompte
from apps.banque.tests.fabriques import (
    FabriqueCompte,
    FabriqueOperation,
    FabriqueReleveSolde,
    FabriqueSousCategorie,
)
from apps.budget.models import LigneBudget
from apps.documents.models import TypeDocument
from apps.documents.tests.fabriques import FabriqueDocument
from apps.foyers.models import Role
from apps.foyers.tests.fabriques import FabriqueAdhesion, FabriqueFoyer
from apps.tableau_de_bord.services import synthese

pytestmark = pytest.mark.django_db

AUJOURD_HUI = date(2026, 3, 20)


@pytest.fixture(autouse=True)
def medias(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def foyer():
    return FabriqueFoyer()


class TestSoldes:
    def test_disponible_et_epargne_sont_separes(self, foyer):
        courant = FabriqueCompte(foyer=foyer, solde_initial=D("1000.00"))
        FabriqueCompte(
            foyer=foyer, type=TypeCompte.LIVRET, est_epargne=True, solde_initial=D("5000")
        )
        pea = FabriqueCompte(foyer=foyer, type=TypeCompte.PEA, est_epargne=True)
        FabriqueReleveSolde(compte=pea, date=date(2026, 2, 28), montant=D("2500.00"))
        FabriqueOperation(compte=courant, date=date(2026, 3, 5), montant=D("-200.00"))

        resultat = synthese(foyer, AUJOURD_HUI)

        assert resultat.disponible == D("800.00")
        assert resultat.epargne == D("7500.00")

    def test_les_operations_futures_et_les_comptes_archives_sont_ignores(self, foyer):
        courant = FabriqueCompte(foyer=foyer, solde_initial=D("100.00"))
        FabriqueOperation(compte=courant, date=date(2026, 4, 1), montant=D("-50.00"))
        FabriqueCompte(foyer=foyer, solde_initial=D("999"), archive_le="2026-01-01T00:00Z")

        resultat = synthese(foyer, AUJOURD_HUI)

        assert [ligne.compte for ligne in resultat.comptes] == [courant]
        assert resultat.disponible == D("100.00")
        assert resultat.dernieres_operations == []

    def test_un_autre_foyer_ne_compte_pas(self, foyer):
        FabriqueCompte(solde_initial=D("1000000"))

        assert synthese(foyer, AUJOURD_HUI).comptes == []


class TestFactures:
    def test_factures_a_payer_les_plus_urgentes_d_abord(self, foyer):
        sans_echeance = FabriqueDocument(foyer=foyer, montant=D("10"))
        en_retard = FabriqueDocument(foyer=foyer, montant=D("20"), echeance=date(2026, 3, 1))
        a_venir = FabriqueDocument(foyer=foyer, montant=D("30"), echeance=date(2026, 3, 25))
        FabriqueDocument(foyer=foyer, montant=D("40"), paye_le=date(2026, 3, 2))
        FabriqueDocument(foyer=foyer, type=TypeDocument.CONTRAT)
        FabriqueDocument(montant=D("1000"))

        resultat = synthese(foyer, AUJOURD_HUI)

        assert [f.document for f in resultat.factures] == [en_retard, a_venir, sans_echeance]
        assert [f.en_retard for f in resultat.factures] == [True, False, False]
        assert (resultat.nombre_factures, resultat.montant_factures) == (3, D("60"))


class TestBudget:
    def test_budget_restant_et_depassements(self, foyer):
        # Même parente : son budget (500) n'est pas dépassé, seule « Sorties » l'est.
        courses = FabriqueSousCategorie(parent__foyer=foyer, nom="Courses")
        sorties = FabriqueSousCategorie(parent=courses.parent, nom="Sorties")
        compte = FabriqueCompte(foyer=foyer)
        for categorie, budget in ((courses, "400"), (sorties, "100")):
            LigneBudget.objects.create(
                foyer=foyer, categorie=categorie, mois=date(2026, 3, 1), montant=D(budget)
            )
        FabriqueOperation(
            compte=compte, categorie=courses, montant=D("-150"), date=date(2026, 3, 3)
        )
        FabriqueOperation(
            compte=compte, categorie=sorties, montant=D("-130"), date=date(2026, 3, 4)
        )

        resultat = synthese(foyer, AUJOURD_HUI)

        assert resultat.budget_restant == D("220")
        assert [(ligne.categorie, ligne.montant_depasse) for ligne in resultat.alertes] == [
            (sorties, D("30"))
        ]

    def test_sans_budget_le_reste_est_indefini(self, foyer):
        assert synthese(foyer, AUJOURD_HUI).budget_restant is None


class TestVue:
    def test_accueil_d_un_membre(self, client):
        adhesion = FabriqueAdhesion(role=Role.LECTEUR, est_principal=True)
        FabriqueCompte(foyer=adhesion.foyer, nom="Compte commun")
        FabriqueDocument(foyer=adhesion.foyer, titre="Facture d'eau")
        FabriqueCompte(nom="Compte d'autrui")
        client.force_login(adhesion.utilisateur)

        contenu = client.get(reverse("accueil")).content.decode()

        assert "Compte commun" in contenu and "Facture d" in contenu
        assert "autrui" not in contenu

    def test_foyer_vide_invite_a_creer_un_compte(self, client):
        adhesion = FabriqueAdhesion(role=Role.MEMBRE, est_principal=True)
        client.force_login(adhesion.utilisateur)

        assert "Ajouter un compte" in client.get(reverse("accueil")).content.decode()
