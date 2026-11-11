from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.banque.tests.fabriques import FabriqueCompte
from apps.foyers.models import Role
from apps.foyers.tests.fabriques import acces_a, espace_de, voir_espace
from apps.prets.models import Pret, RemboursementAnticipe
from apps.prets.services.encours import encours_du_foyer, total_biens, total_dettes
from apps.tableau_de_bord.services import synthese

from .fabriques import FabriquePret, FabriqueRemboursement

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(client):
    adhesion = espace_de()
    client.force_login(adhesion.utilisateur)
    return adhesion


DONNEES = {
    "nom": "Crédit immobilier",
    "etablissement": "Société Générale",
    "capital": "200000",
    "taux_annuel": "3.5",  # le champ numérique du navigateur envoie un point
    "duree_mois": "300",
    "premiere_echeance": "2026-01-05",
    "assurance_mensuelle": "44.68",
    "type_differe": "aucun",
    "differe_mois": "0",
    "valeur_bien": "250000",
}


class TestSaisie:
    def test_creer_un_pret(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer)

        reponse = client.post(reverse("prets:ajouter"), DONNEES | {"compte": compte.pk})

        pret = Pret.objects.get()
        assert reponse.url == reverse("prets:pret", args=[pret.pk])
        assert (pret.foyer, pret.compte, pret.taux_annuel) == (alice.foyer, compte, D("3.5"))

    def test_differe_sans_duree_refuse(self, client, alice):
        reponse = client.post(reverse("prets:ajouter"), DONNEES | {"type_differe": "total"})

        assert reponse.status_code == 200 and not Pret.objects.exists()

    def test_differe_trop_long_refuse(self, client, alice):
        client.post(
            reverse("prets:ajouter"),
            DONNEES | {"type_differe": "partiel", "differe_mois": "300"},
        )

        assert not Pret.objects.exists()

    def test_sans_differe_la_duree_du_differe_est_ignoree(self, client, alice):
        client.post(reverse("prets:ajouter"), DONNEES | {"differe_mois": "12"})

        assert Pret.objects.get().differe_mois == 0

    def test_pages_affichees(self, client, alice):
        pret = FabriquePret(foyer=alice.foyer, differe_mois=6, type_differe="partiel")
        FabriqueRemboursement(pret=pret)

        liste = client.get(reverse("prets:liste"))
        detail = client.get(reverse("prets:pret", args=[pret.pk]))

        assert pret.nom in liste.content.decode()
        assert "Tableau d" in detail.content.decode()
        annees = [annee.annee for annee in detail.context["annees"]]
        assert annees == sorted({e.date.year for e in detail.context["tableau"].echeances})
        assert annees[0] == 2026

    def test_liste_vide_puis_pret_rembourse(self, client, alice):
        assert "Suivez vos crédits" in client.get(reverse("prets:liste")).content.decode()

        FabriquePret(foyer=alice.foyer, duree_mois=12, premiere_echeance=date(2020, 1, 1))
        reponse = client.get(reverse("prets:liste"))

        assert len(reponse.context["termines"]) == 1 and not reponse.context["encours"]


class TestModification:
    def test_modifier_et_supprimer(self, client, alice):
        pret = FabriquePret(foyer=alice.foyer)

        reponse = client.post(
            reverse("prets:modifier", args=[pret.pk]), DONNEES | {"nom": "Crédit maison"}
        )
        assert reponse.url == reverse("prets:pret", args=[pret.pk])
        pret.refresh_from_db()
        assert pret.nom == "Crédit maison"

        assert (
            "Supprimer le crédit"
            in client.get(reverse("prets:supprimer", args=[pret.pk])).content.decode()
        )
        client.post(reverse("prets:supprimer", args=[pret.pk]))
        assert not Pret.objects.exists()

    def test_le_compte_doit_etre_du_meme_foyer(self):
        from django.core.exceptions import ValidationError

        pret = FabriquePret.build(compte=FabriqueCompte())

        with pytest.raises(ValidationError):
            pret.clean()

    def test_totaux_par_annee(self, alice):
        from apps.prets.services.encours import par_annee

        pret = FabriquePret(foyer=alice.foyer, assurance_mensuelle=D("10"))
        remboursement = FabriqueRemboursement(pret=pret, date=date(2026, 3, 1))
        annees = par_annee(pret.tableau(), date(2026, 6, 1))

        assert (annees[0].assurance, annees[0].anticipe) == (D("120"), D("20000"))
        assert annees[0].en_cours and not annees[1].en_cours
        assert str(remboursement) == f"{pret} – 01/03/2026"


class TestRemboursementAnticipe:
    def test_simuler_n_enregistre_rien(self, client, alice):
        pret = FabriquePret(foyer=alice.foyer)

        reponse = client.get(
            reverse("prets:pret", args=[pret.pk]),
            {"date": "2031-01-01", "montant": "20000", "effet": "duree"},
        )

        assert reponse.context["simulation"].economie_interets == D("18100.83")
        assert not RemboursementAnticipe.objects.exists()

    def test_enregistrer_puis_supprimer(self, client, alice):
        pret = FabriquePret(foyer=alice.foyer)

        client.post(
            reverse("prets:ajouter_anticipe", args=[pret.pk]),
            {"date": "2031-01-01", "montant": "20000.00", "effet": "mensualite"},
        )
        remboursement = RemboursementAnticipe.objects.get()
        assert (remboursement.foyer, remboursement.pret) == (alice.foyer, pret)
        assert len(pret.tableau().echeances) == 300

        client.post(reverse("prets:supprimer_anticipe", args=[remboursement.pk]))
        assert not RemboursementAnticipe.objects.exists()

    def test_saisie_invalide(self, client, alice):
        pret = FabriquePret(foyer=alice.foyer)

        client.post(reverse("prets:ajouter_anticipe", args=[pret.pk]), {"montant": "-5"})

        assert not RemboursementAnticipe.objects.exists()


ROUTES = [
    ("prets:pret", "pret"),
    ("prets:modifier", "pret"),
    ("prets:supprimer", "pret"),
    ("prets:ajouter_anticipe", "pret"),
    ("prets:supprimer_anticipe", "remboursement"),
]


class TestIsolation:
    @pytest.mark.parametrize(("route", "objet"), ROUTES)
    def test_le_pret_d_autrui_est_introuvable(self, client, alice, route, objet):
        remboursement = FabriqueRemboursement(pret__nom="Crédit secret")
        cibles = {"pret": remboursement.pret, "remboursement": remboursement}
        url = reverse(route, args=[cibles[objet].pk])

        codes = {client.get(url).status_code, client.post(url, DONNEES).status_code}

        assert codes <= {404, 405} and 404 in codes
        assert Pret.objects.get().nom == "Crédit secret"
        assert RemboursementAnticipe.objects.count() == 1

    def test_la_liste_ne_montre_que_le_foyer_courant(self, client, alice):
        FabriquePret(nom="Crédit secret")

        assert "secret" not in client.get(reverse("prets:liste")).content.decode()

    def test_compte_d_autrui_refuse(self, client, alice):
        client.post(reverse("prets:ajouter"), DONNEES | {"compte": FabriqueCompte().pk})

        assert not Pret.objects.exists()

    def test_un_lecteur_consulte_sans_modifier(self, client):
        proprietaire = espace_de()
        lecteur = acces_a(proprietaire, Role.LECTEUR)
        pret = FabriquePret(foyer=proprietaire.foyer)
        client.force_login(lecteur.utilisateur)
        voir_espace(client, proprietaire)

        assert client.get(reverse("prets:pret", args=[pret.pk])).status_code == 200
        assert client.post(reverse("prets:ajouter"), DONNEES).status_code == 403
        assert client.post(reverse("prets:ajouter_anticipe", args=[pret.pk]), {}).status_code == 403


class TestPatrimoineNet:
    def test_dettes_et_biens_dans_la_synthese(self, alice):
        FabriqueCompte(foyer=alice.foyer, solde_initial=D("10000"), ouvert_le=date(2026, 1, 1))
        FabriquePret(foyer=alice.foyer, valeur_bien=D("250000"))
        FabriquePret(foyer=alice.foyer, capital=D("5000"), duree_mois=12)

        resultat = synthese(alice.foyer, date(2025, 12, 31))

        assert resultat.dettes == D("205000")
        assert resultat.biens == D("250000")
        assert resultat.patrimoine_net == D("10000") + D("250000") - D("205000")
        assert resultat.a_des_credits

    def test_le_bien_n_est_compte_qu_a_partir_de_l_achat(self, alice):
        FabriquePret(foyer=alice.foyer, valeur_bien=D("250000"))

        assert total_biens(encours_du_foyer(alice.foyer, date(2025, 11, 30))) == 0
        assert total_biens(encours_du_foyer(alice.foyer, date(2025, 12, 5))) == D("250000")

    def test_un_pret_qui_n_a_pas_commence_ne_pese_pas_et_n_est_pas_termine(self, alice):
        FabriquePret(foyer=alice.foyer, valeur_bien=D("250000"), premiere_echeance=date(2027, 1, 5))

        encours = encours_du_foyer(alice.foyer, date(2026, 6, 1))

        assert total_dettes(encours) == total_biens(encours) == 0
        assert not encours[0].est_termine and encours[0].part_remboursee == 0

    def test_sans_credit(self, alice):
        resultat = synthese(alice.foyer, date(2026, 1, 1))

        assert not resultat.a_des_credits
        assert total_dettes([]) == 0
