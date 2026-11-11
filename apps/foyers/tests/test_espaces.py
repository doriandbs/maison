"""Espaces financiers personnels et accès croisés entre membres d'un foyer (ADR 0006)."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.banque.models import Categorie, Compte
from apps.banque.tests.fabriques import FabriqueCompte
from apps.foyers.espaces import acces_aux_espaces, espace_personnel
from apps.foyers.middleware import CLE_SESSION_ESPACE, CLE_SESSION_FOYER
from apps.foyers.models import Adhesion, Foyer, Role
from apps.utilisateurs.tests.fabriques import FabriqueUtilisateur

from .fabriques import FabriqueAdhesion, FabriqueFoyer, acces_a, espace_de, voir_espace

pytestmark = pytest.mark.django_db


class TestEspacePersonnel:
    def test_cree_a_la_premiere_connexion_avec_les_categories(self, client):
        alice = FabriqueUtilisateur(first_name="Alice")
        client.force_login(alice)

        client.get(reverse("accueil"))

        espace = Foyer.objects.get(personne=alice)
        assert espace.nom == "Finances de Alice"
        assert Adhesion.objects.get(foyer=espace).role == Role.PROPRIETAIRE
        assert Categorie.objects.du_foyer(espace).exists()

    def test_unique_et_stable(self):
        alice = FabriqueUtilisateur()

        assert espace_personnel(alice) == espace_personnel(alice)
        assert Foyer.objects.filter(personne=alice).count() == 1

    def test_on_cree_ses_comptes_sans_aucun_foyer(self, client):
        alice = espace_de()
        client.force_login(alice.utilisateur)

        client.post(
            reverse("banque:ajouter_compte"),
            {"nom": "Courant", "type": "courant", "solde_initial": "10", "ouvert_le": "2026-01-01"},
        )

        assert Compte.objects.get().foyer == alice.foyer

    def test_n_est_jamais_presente_comme_un_foyer(self, client):
        alice = espace_de()
        client.force_login(alice.utilisateur)

        assert client.post(reverse("foyers:activer", args=[alice.foyer_id])).status_code == 404
        assert client.post(reverse("foyers:principal", args=[alice.foyer_id])).status_code == 404
        assert client.get(reverse("accueil")).context["adhesions"] == []


class TestAccesCroise:
    def test_un_membre_voit_et_gere_les_finances_des_autres(self, client):
        dorian = espace_de(FabriqueUtilisateur(first_name="Dorian"))
        compte = FabriqueCompte(foyer=dorian.foyer, nom="Courant SG Dorian")
        alexandra = acces_a(dorian, Role.MEMBRE)
        client.force_login(alexandra.utilisateur)

        espaces = client.get(reverse("accueil")).context["espaces"]
        assert [e.foyer for e in espaces][1:] == [dorian.foyer]
        client.post(reverse("foyers:espace", args=[dorian.foyer_id]))
        assert "Courant SG Dorian" in client.get(reverse("banque:comptes")).content.decode()

        client.post(
            reverse("banque:modifier_compte", args=[compte.pk]),
            {
                "nom": "Courant SG",
                "type": "courant",
                "solde_initial": "0",
                "ouvert_le": "2026-01-01",
            },
        )
        compte.refresh_from_db()
        assert compte.nom == "Courant SG"

    def test_le_role_dans_le_foyer_s_applique_aux_espaces_des_membres(self):
        dorian = espace_de()
        lectrice = acces_a(dorian, Role.LECTEUR)

        acces = acces_aux_espaces(lectrice.utilisateur, lectrice.foyer)

        assert acces[0].role == Role.PROPRIETAIRE  # son propre espace
        assert (acces[1].foyer, acces[1].role) == (dorian.foyer, Role.LECTEUR)
        assert acces[1].pk is None  # adhésion calculée, jamais enregistrée

    def test_seuls_les_membres_du_foyer_courant_sont_proposes(self, client):
        dorian = espace_de()
        alexandra = acces_a(dorian)
        parents = FabriqueAdhesion(utilisateur=alexandra.utilisateur, foyer__nom="Parents")
        mere = FabriqueAdhesion(foyer=parents.foyer)
        client.force_login(alexandra.utilisateur)

        dans_le_couple = {e.foyer.personne for e in client.get("/").context["espaces"]}
        session = client.session
        session[CLE_SESSION_FOYER] = parents.foyer_id
        session.save()
        chez_les_parents = {e.foyer.personne for e in client.get("/").context["espaces"]}

        assert dans_le_couple == {alexandra.utilisateur, dorian.utilisateur}
        assert chez_les_parents == {alexandra.utilisateur, mere.utilisateur}


def _membre_d_un_foyer():
    """Quelqu'un qui partage un foyer avec un proche : l'accès croisé est actif pour lui,
    c'est donc là qu'une fuite vers l'espace d'un inconnu se produirait."""
    return acces_a(espace_de())


class TestIsolation:
    def test_impossible_de_choisir_l_espace_d_un_inconnu(self, client):
        inconnu = espace_de()
        alice = _membre_d_un_foyer()
        client.force_login(alice.utilisateur)

        assert client.post(reverse("foyers:espace", args=[inconnu.foyer_id])).status_code == 404
        assert client.session.get(CLE_SESSION_ESPACE) != inconnu.foyer_id

    def test_une_session_falsifiee_retombe_sur_son_propre_espace(self, client):
        inconnu = espace_de()
        FabriqueCompte(foyer=inconnu.foyer, nom="Compte secret")
        alice = _membre_d_un_foyer()
        client.force_login(alice.utilisateur)
        voir_espace(client, inconnu)

        reponse = client.get(reverse("banque:comptes"))

        assert reponse.context["adhesion_espace"].foyer.personne == alice.utilisateur
        assert inconnu.foyer not in [e.foyer for e in reponse.context["espaces"]]
        assert "secret" not in reponse.content.decode()

    def test_les_objets_d_un_inconnu_restent_introuvables(self, client):
        compte = FabriqueCompte(foyer=espace_de().foyer)
        client.force_login(_membre_d_un_foyer().utilisateur)

        assert client.get(reverse("banque:compte", args=[compte.pk])).status_code == 404

    def test_un_membre_retire_perd_aussitot_l_acces(self, client):
        dorian = espace_de()
        FabriqueCompte(foyer=dorian.foyer, nom="Compte de Dorian")
        ex = acces_a(dorian)
        client.force_login(ex.utilisateur)
        voir_espace(client, dorian)
        assert "Compte de Dorian" in client.get(reverse("banque:comptes")).content.decode()

        ex.delete()

        reponse = client.get(reverse("banque:comptes"))
        assert reponse.context["adhesion_espace"].foyer.personne == ex.utilisateur
        assert "Dorian" not in reponse.content.decode()

    def test_un_lecteur_ne_modifie_pas_l_espace_d_un_membre(self, client):
        dorian = espace_de()
        compte = FabriqueCompte(
            foyer=dorian.foyer, solde_initial=D("10"), ouvert_le=date(2026, 1, 1)
        )
        lecteur = acces_a(dorian, Role.LECTEUR)
        client.force_login(lecteur.utilisateur)
        voir_espace(client, dorian)

        assert client.get(reverse("banque:comptes")).status_code == 200
        assert client.post(reverse("banque:archiver_compte", args=[compte.pk])).status_code == 403

    def test_un_foyer_partage_ne_donne_pas_acces_a_un_autre_foyer_partage(self, client):
        dorian = espace_de()
        alexandra = acces_a(dorian)
        autre_foyer = FabriqueFoyer()
        client.force_login(alexandra.utilisateur)
        session = client.session
        session[CLE_SESSION_FOYER] = autre_foyer.pk
        session.save()

        reponse = client.get(reverse("documents:liste"))

        assert reponse.context["adhesion_courante"].foyer == alexandra.foyer
