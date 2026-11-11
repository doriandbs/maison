from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.banque.tests.fabriques import FabriqueCompte, FabriqueOperation
from apps.budget.services.comparaison import histogramme_annuel
from apps.budget.services.recap import recap_annuel
from apps.foyers.tests.fabriques import FabriqueFoyer, espace_de
from apps.prets.tests.fabriques import FabriquePret
from apps.tableau_de_bord import patrimoine

pytestmark = pytest.mark.django_db

AUJOURD_HUI = date(2026, 6, 15)


class TestEvolution:
    def test_fins_de_mois_puis_aujourd_hui(self):
        foyer = FabriqueFoyer()
        compte = FabriqueCompte(foyer=foyer, solde_initial=D("1000"), ouvert_le=date(2025, 1, 1))
        FabriqueOperation(compte=compte, date=date(2026, 5, 31), montant=D("500"))
        FabriqueOperation(compte=compte, date=date(2026, 6, 10), montant=D("-200"))

        points = patrimoine.evolution(foyer, 12, AUJOURD_HUI)

        assert len(points) == 12
        assert points[0].date == date(2025, 7, 31)
        assert points[-2].date == date(2026, 5, 31) and points[-2].valeur == D("1500")
        assert points[-1].date == AUJOURD_HUI and points[-1].en_cours
        assert points[-1].valeur == D("1300")

    def test_un_compte_ne_compte_qu_apres_son_ouverture(self):
        foyer = FabriqueFoyer()
        FabriqueCompte(foyer=foyer, solde_initial=D("1000"), ouvert_le=date(2026, 3, 10))
        FabriqueCompte(foyer=foyer, solde_initial=D("50"), ouvert_le=date(2026, 5, 1))

        points = patrimoine.evolution(foyer, 12, AUJOURD_HUI)

        assert [p.date for p in points] == [
            date(2026, 3, 31),
            date(2026, 4, 30),
            date(2026, 5, 31),
            AUJOURD_HUI,
        ]
        assert [p.valeur for p in points] == [D("1000"), D("1000"), D("1050"), D("1050")]

    def test_credits_et_biens_dans_le_patrimoine_net(self):
        foyer = FabriqueFoyer()
        FabriqueCompte(foyer=foyer, solde_initial=D("10000"), ouvert_le=date(2025, 1, 1))
        # Le bien compte à partir du mois qui précède la 1re échéance (achat), ici le 5 mai.
        FabriquePret(foyer=foyer, valeur_bien=D("250000"), premiere_echeance=date(2026, 6, 5))

        points = patrimoine.evolution(foyer, 3, AUJOURD_HUI)

        avril, mai, aujourd_hui = points
        assert avril.valeur == D("10000")
        assert mai.valeur == D("10000") + D("250000") - D("200000")
        assert aujourd_hui.valeur > mai.valeur  # une échéance payée : capital dû en baisse

    def test_foyer_sans_compte(self):
        assert patrimoine.evolution(FabriqueFoyer(), 12, AUJOURD_HUI) == []
        assert patrimoine.graphique([]) is None


class TestEcrans:
    @pytest.fixture
    def membre(self, client):
        adhesion = espace_de()
        client.force_login(adhesion.utilisateur)
        FabriqueCompte(foyer=adhesion.foyer, solde_initial=D("100"), ouvert_le=date(2024, 1, 1))
        return adhesion

    @pytest.mark.parametrize(("parametre", "attendu"), [("24", 24), ("6", 12), (None, 12)])
    def test_periode_de_la_courbe(self, client, membre, parametre, attendu):
        reponse = client.get(reverse("accueil"), {"periode": parametre} if parametre else {})

        assert reponse.context["periode"] == attendu
        assert len(reponse.context["evolution"]) == attendu
        assert 'class="graphique"' in reponse.content.decode()

    @pytest.mark.parametrize(("parametre", "attendu"), [("revenus", "revenus"), ("x", "depenses")])
    def test_comparaison_annuelle(self, client, membre, parametre, attendu):
        compte = membre.foyer and FabriqueCompte(foyer=membre.foyer, ouvert_le=date(2024, 1, 1))
        FabriqueOperation(compte=compte, date=date(2025, 3, 3), montant=D("-80"))
        FabriqueOperation(compte=compte, date=date(2025, 3, 4), montant=D("900"))

        reponse = client.get(reverse("budget:annee", args=[2025]), {"mesure": parametre})

        assert reponse.context["mesure"] == attendu
        assert reponse.context["histogramme"] is not None


def test_histogramme_annuel_mois_futurs_vides():
    foyer = FabriqueFoyer()
    compte = FabriqueCompte(foyer=foyer, ouvert_le=date(2024, 1, 1))
    FabriqueOperation(compte=compte, date=date(2026, 2, 3), montant=D("-80"))
    FabriqueOperation(compte=compte, date=date(2025, 11, 3), montant=D("-50"))

    resultat = histogramme_annuel(
        recap_annuel(foyer, 2026), recap_annuel(foyer, 2025), "depenses", date(2026, 3, 1)
    )

    fevrier, novembre = resultat.groupes[1], resultat.groupes[10]
    assert [b.serie for b in fevrier.barres] == [1]
    assert [b.serie for b in novembre.barres] == [2]
    assert "2026 : –" in novembre.infobulle
