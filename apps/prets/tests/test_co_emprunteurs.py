from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.foyers.models import Role
from apps.foyers.tests.fabriques import acces_a, espace_de
from apps.prets.models import Pret, RemboursementAnticipe
from apps.prets.services.encours import encours_du_foyer, total_biens, total_dettes
from apps.utilisateurs.tests.fabriques import FabriqueUtilisateur

from .fabriques import FabriquePret, FabriqueRemboursement

pytestmark = pytest.mark.django_db

DONNEES = {
    "nom": "Crédit immobilier",
    "capital": "200000",
    "taux_annuel": "3.5",
    "duree_mois": "300",
    "premiere_echeance": "2026-01-05",
    "assurance_mensuelle": "0",
    "type_differe": "aucun",
    "differe_mois": "0",
}


@pytest.fixture
def couple():
    """Dorian a saisi le crédit ; Alexandra partage le foyer « Maison » avec lui."""
    dorian = espace_de(FabriqueUtilisateur(first_name="Dorian"))
    foyer_commun = acces_a(dorian, Role.MEMBRE)
    alexandra = espace_de(foyer_commun.utilisateur)
    return dorian, alexandra, foyer_commun


def _credit_a_deux(dorian, alexandra, **champs):
    pret = FabriquePret(foyer=dorian.foyer, valeur_bien=D("300000"), **champs)
    pret.co_emprunteurs.set([alexandra.utilisateur])
    return pret


class TestSaisie:
    def test_on_ajoute_un_proche_comme_co_emprunteur(self, client, couple):
        dorian, alexandra, _ = couple
        client.force_login(dorian.utilisateur)

        client.post(
            reverse("prets:ajouter"), DONNEES | {"co_emprunteurs": [alexandra.utilisateur.pk]}
        )

        assert list(Pret.objects.get().co_emprunteurs.all()) == [alexandra.utilisateur]

    def test_impossible_d_ajouter_un_inconnu(self, client, couple):
        dorian, _, _ = couple
        inconnu = FabriqueUtilisateur()
        client.force_login(dorian.utilisateur)

        reponse = client.post(reverse("prets:ajouter"), DONNEES | {"co_emprunteurs": [inconnu.pk]})

        assert reponse.status_code == 200 and not Pret.objects.exists()

    def test_seuls_les_proches_sont_proposes(self, client, couple):
        dorian, alexandra, _ = couple
        FabriqueUtilisateur()
        client.force_login(dorian.utilisateur)

        champ = client.get(reverse("prets:ajouter")).context["form"].fields["co_emprunteurs"]

        assert list(champ.queryset) == [alexandra.utilisateur]


class TestVisibilite:
    def test_le_co_emprunteur_le_voit_dans_ses_credits(self, client, couple):
        dorian, alexandra, _ = couple
        pret = _credit_a_deux(dorian, alexandra, nom="Maison de Poissy")
        client.force_login(alexandra.utilisateur)

        liste = client.get(reverse("prets:liste")).content.decode()
        detail = client.get(reverse("prets:pret", args=[pret.pk]))

        assert "Maison de Poissy" in liste
        assert detail.status_code == 200

    def test_le_co_emprunteur_a_les_memes_droits(self, client, couple):
        dorian, alexandra, _ = couple
        pret = _credit_a_deux(dorian, alexandra)
        client.force_login(alexandra.utilisateur)
        client.get("/")  # crée son espace

        client.post(
            reverse("prets:ajouter_anticipe", args=[pret.pk]),
            {"date": "2030-01-01", "montant": "1000", "effet": "duree"},
        )
        assert RemboursementAnticipe.objects.get().pret == pret
        client.post(
            reverse("prets:modifier", args=[pret.pk]),
            DONNEES | {"nom": "Renommé", "co_emprunteurs": [alexandra.utilisateur.pk]},
        )
        pret.refresh_from_db()
        assert pret.nom == "Renommé" and pret.foyer == dorian.foyer
        client.post(reverse("prets:supprimer", args=[pret.pk]))
        assert not Pret.objects.exists()

    def test_hors_du_foyer_le_co_emprunteur_le_garde(self, client):
        """Même sans foyer commun courant, le co-emprunteur voit et modifie le prêt."""
        dorian = espace_de()
        alexandra = espace_de()
        pret = _credit_a_deux(dorian, alexandra)
        client.force_login(alexandra.utilisateur)

        assert client.get(reverse("prets:pret", args=[pret.pk])).status_code == 200
        client.post(reverse("prets:modifier", args=[pret.pk]), DONNEES | {"nom": "Ailleurs"})
        pret.refresh_from_db()
        assert pret.nom == "Ailleurs"

    def test_un_tiers_ne_voit_rien(self, client, couple):
        dorian, alexandra, _ = couple
        pret = _credit_a_deux(dorian, alexandra)
        remboursement = FabriqueRemboursement(pret=pret)
        client.force_login(espace_de().utilisateur)

        assert client.get(reverse("prets:pret", args=[pret.pk])).status_code == 404
        reponse = client.post(reverse("prets:supprimer_anticipe", args=[remboursement.pk]))
        assert reponse.status_code == 404


class TestPatrimoine:
    def test_chacun_le_compte_en_entier(self, couple):
        dorian, alexandra, _ = couple
        _credit_a_deux(dorian, alexandra, signe_le=date(2025, 12, 1))
        jour = date(2025, 12, 15)

        pour_dorian = encours_du_foyer(dorian.foyer, jour)
        pour_alexandra = encours_du_foyer(alexandra.foyer, jour)

        assert total_dettes(pour_dorian) == total_dettes(pour_alexandra) == D("200000")
        assert total_biens(pour_dorian) == total_biens(pour_alexandra) == D("300000")

    def test_le_foyer_ne_le_compte_qu_une_fois(self, client, couple):
        dorian, alexandra, _ = couple
        _credit_a_deux(dorian, alexandra, signe_le=date(2025, 12, 1))
        client.force_login(alexandra.utilisateur)

        synthese = client.get("/").context["synthese"]

        un_seul = total_dettes(encours_du_foyer(dorian.foyer, synthese.aujourd_hui))
        assert synthese.dettes == un_seul and synthese.biens == D("300000")
