from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.banque.tests.fabriques import FabriqueSousCategorie
from apps.budget.models import LigneBudget
from apps.budget.services.previsionnel import budgets_du_mois
from apps.foyers.models import Adhesion, Role
from apps.foyers.tests.fabriques import acces_a, espace_de, voir_espace

from .fabriques import FabriqueLigneBudget

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def membre(client, mars):
    """Le titulaire de l'espace où se trouvent les données de mars."""
    adhesion = Adhesion.objects.get(foyer=mars.foyer, utilisateur=mars.foyer.personne)
    client.force_login(adhesion.utilisateur)
    return adhesion


def _champ(categorie) -> str:
    return f"categorie_{categorie.pk}"


class TestTableauMensuel:
    def test_budget_redirige_vers_le_mois_courant(self, client, membre):
        aujourd_hui = date.today()

        reponse = client.get(reverse("budget:courant"))

        assert reponse["Location"] == reverse(
            "budget:mois", args=[aujourd_hui.year, aujourd_hui.month]
        )

    def test_affiche_le_mois(self, client, membre, mars):
        FabriqueLigneBudget(categorie=mars.electricite, montant=D("120.00"))

        reponse = client.get(reverse("budget:mois", args=[2026, 3]))
        contenu = reponse.content.decode()

        assert reponse.context["tableau"].flux.depenses == D("343.00")
        assert "Budgets dépassés" in contenu and "Électricité" in contenu
        assert "82,9 %" in contenu
        assert reverse("budget:mois", args=[2026, 2]) in contenu
        assert reverse("budget:mois", args=[2026, 4]) in contenu

    def test_navigation_au_passage_d_annee(self, client, membre):
        decembre = client.get(reverse("budget:mois", args=[2026, 12]))
        janvier = client.get(reverse("budget:mois", args=[2026, 1]))

        assert decembre.context["mois_suivant"] == date(2027, 1, 1)
        assert janvier.context["mois_precedent"] == date(2025, 12, 1)

    @pytest.mark.parametrize(("annee", "mois"), [(2026, 13), (2026, 0), (1999, 1), (2101, 1)])
    def test_mois_ou_annee_hors_limites(self, client, membre, annee, mois):
        assert client.get(reverse("budget:mois", args=[annee, mois])).status_code == 404
        assert client.get(reverse("budget:previsionnel", args=[annee, mois])).status_code == 404

    def test_les_donnees_d_un_autre_foyer_n_apparaissent_pas(self, client, mars):
        etranger = espace_de()  # son propre espace, vide
        client.force_login(etranger.utilisateur)

        reponse = client.get(reverse("budget:mois", args=[2026, 3]))

        assert reponse.context["tableau"].flux.revenus == D("0.00")
        assert "Électricité" not in reponse.content.decode()


class TestRecapAnnuel:
    def test_affiche_l_annee(self, client, membre):
        reponse = client.get(reverse("budget:annee", args=[2026]))
        contenu = reponse.content.decode()

        assert reponse.context["recap"].total.revenus == D("2000.00")
        assert "Récapitulatif 2026" in contenu and "Énergie" in contenu
        assert reverse("budget:annee", args=[2025]) in contenu

    def test_annee_hors_limites(self, client, membre):
        assert client.get(reverse("budget:annee", args=[1999])).status_code == 404

    def test_les_donnees_d_un_autre_foyer_n_apparaissent_pas(self, client, mars):
        client.force_login(espace_de().utilisateur)

        reponse = client.get(reverse("budget:annee", args=[2026]))

        assert reponse.context["recap"].total.revenus == D("0.00")
        assert reponse.context["recap"].comptes == []


class TestPrevisionnel:
    def test_le_formulaire_reprend_les_budgets_en_vigueur(self, client, membre, mars):
        FabriqueLigneBudget(categorie=mars.electricite, montant=D("120.00"))

        reponse = client.get(reverse("budget:previsionnel", args=[2026, 3]))
        formulaire = reponse.context["form"]

        assert formulaire[_champ(mars.electricite)].initial == D("120.00")
        assert _champ(mars.salaire) not in formulaire.fields
        groupes = {
            parent.label: [c.label for c in enfants] for parent, enfants in formulaire.groupes()
        }
        assert groupes == {"Énergie": ["Électricité", "Gaz"], "Loisirs": ["Sorties"]}

    def test_enregistrer_a_partir_du_mois(self, client, membre, mars):
        reponse = client.post(
            reverse("budget:previsionnel", args=[2026, 3]),
            {"portee": "suivants", _champ(mars.electricite): "120", _champ(mars.loisirs): "250"},
        )

        assert reponse["Location"] == reverse("budget:mois", args=[2026, 3])
        assert budgets_du_mois(mars.foyer, date(2026, 5, 1)) == {
            mars.electricite.pk: D("120.00"),
            mars.loisirs.pk: D("250.00"),
        }

    def test_enregistrer_pour_ce_mois_uniquement(self, client, membre, mars):
        client.post(
            reverse("budget:previsionnel", args=[2026, 8]),
            {"portee": "ponctuel", _champ(mars.sorties): "600"},
        )

        assert budgets_du_mois(mars.foyer, date(2026, 8, 1)) == {mars.sorties.pk: D("600.00")}
        assert budgets_du_mois(mars.foyer, date(2026, 9, 1)) == {}

    def test_montant_negatif_refuse(self, client, membre, mars):
        reponse = client.post(
            reverse("budget:previsionnel", args=[2026, 3]),
            {"portee": "suivants", _champ(mars.gaz): "-5"},
        )

        assert reponse.status_code == 200
        assert not LigneBudget.objects.exists()

    def test_la_categorie_d_un_autre_foyer_est_ignoree(self, client, membre, mars):
        etrangere = FabriqueSousCategorie()

        client.post(
            reverse("budget:previsionnel", args=[2026, 3]),
            {"portee": "suivants", _champ(etrangere): "999"},
        )

        assert not LigneBudget.objects.exists()

    def test_un_lecteur_ne_peut_pas_modifier_le_previsionnel(self, client, mars):
        proprietaire = Adhesion.objects.get(foyer=mars.foyer, utilisateur=mars.foyer.personne)
        lecteur = acces_a(proprietaire, Role.LECTEUR)
        client.force_login(lecteur.utilisateur)
        voir_espace(client, proprietaire)

        reponse = client.post(
            reverse("budget:previsionnel", args=[2026, 3]),
            {"portee": "suivants", _champ(mars.gaz): "70"},
        )
        tableau = client.get(reverse("budget:mois", args=[2026, 3]))

        assert reponse.status_code == 403
        assert not LigneBudget.objects.exists()
        assert "Modifier le prévisionnel" not in tableau.content.decode()
