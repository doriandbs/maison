import re
from types import SimpleNamespace

import pytest
from django.core import mail
from django.urls import reverse

from apps.foyers.middleware import CLE_SESSION_FOYER
from apps.foyers.models import Adhesion, Foyer, Invitation, Role
from apps.utilisateurs.tests.fabriques import MOT_DE_PASSE, FabriqueUtilisateur

from .fabriques import FabriqueAdhesion, FabriqueFoyer, FabriqueInvitation

pytestmark = pytest.mark.django_db


@pytest.fixture
def monde():
    """Deux foyers étanches : celui d'Alice, et celui de Bob où Carl est membre."""
    foyer_a, foyer_b = FabriqueFoyer(nom="Foyer A"), FabriqueFoyer(nom="Foyer B")
    alice = FabriqueAdhesion(foyer=foyer_a, role=Role.PROPRIETAIRE, est_principal=True)
    bob = FabriqueAdhesion(foyer=foyer_b, role=Role.PROPRIETAIRE, est_principal=True)
    carl = FabriqueAdhesion(foyer=foyer_b, role=Role.MEMBRE, est_principal=True)
    invitation_b = FabriqueInvitation(foyer=foyer_b, email="dora@example.org")
    return SimpleNamespace(
        foyer_a=foyer_a, foyer_b=foyer_b, alice=alice, bob=bob, carl=carl, invitation_b=invitation_b
    )


def _client_de(client, adhesion: Adhesion):
    client.force_login(adhesion.utilisateur)
    return client


class TestIsolationEntreFoyers:
    """Alice (propriétaire du foyer A) ne voit ni ne modifie rien du foyer B."""

    def test_ne_peut_pas_ouvrir_le_foyer_d_autrui(self, client, monde):
        client = _client_de(client, monde.alice)

        reponse = client.post(reverse("foyers:activer", args=[monde.foyer_b.pk]))

        assert reponse.status_code == 404
        assert client.session.get(CLE_SESSION_FOYER) != monde.foyer_b.pk

    def test_ne_peut_pas_en_faire_son_foyer_principal(self, client, monde):
        reponse = _client_de(client, monde.alice).post(
            reverse("foyers:principal", args=[monde.foyer_b.pk])
        )

        assert reponse.status_code == 404

    def test_une_session_falsifiee_retombe_sur_son_propre_foyer(self, client, monde):
        client = _client_de(client, monde.alice)
        session = client.session
        session[CLE_SESSION_FOYER] = monde.foyer_b.pk
        session.save()

        reponse = client.get(reverse("foyers:membres"))

        assert reponse.context["adhesion_courante"] == monde.alice
        contenu = reponse.content.decode()
        assert monde.bob.utilisateur.email not in contenu
        assert monde.invitation_b.email not in contenu

    def test_ne_peut_pas_changer_le_role_d_un_membre_d_autrui(self, client, monde):
        reponse = _client_de(client, monde.alice).post(
            reverse("foyers:changer_role", args=[monde.carl.pk]), {"role": Role.LECTEUR}
        )

        monde.carl.refresh_from_db()
        assert reponse.status_code == 404
        assert monde.carl.role == Role.MEMBRE

    def test_ne_peut_pas_retirer_un_membre_d_autrui(self, client, monde):
        reponse = _client_de(client, monde.alice).post(
            reverse("foyers:retirer_membre", args=[monde.carl.pk])
        )

        assert reponse.status_code == 404
        assert Adhesion.objects.filter(pk=monde.carl.pk).exists()

    def test_ne_peut_pas_revoquer_une_invitation_d_autrui(self, client, monde):
        reponse = _client_de(client, monde.alice).post(
            reverse("foyers:revoquer_invitation", args=[monde.invitation_b.pk])
        )

        monde.invitation_b.refresh_from_db()
        assert reponse.status_code == 404
        assert monde.invitation_b.est_en_attente

    def test_un_compte_a_l_adresse_invitee_ne_rejoint_pas_sans_le_lien(self, client):
        """L'inscription ne confirme pas l'adresse : un imposteur peut créer un compte avec
        celle de l'invité. Sans le lien reçu par e-mail, il ne voit ni ne rejoint rien."""
        invitation = FabriqueInvitation(email="victime@example.org")
        client.force_login(FabriqueUtilisateur(email="victime@example.org"))

        liste = client.get(reverse("foyers:liste")).content.decode()
        ancienne_route = client.post(f"/invitations/{invitation.pk}/accepter/")

        assert invitation.foyer.nom not in liste
        assert ancienne_route.status_code == 404
        assert not Adhesion.objects.filter(foyer=invitation.foyer).exists()

    def test_un_lien_d_invitation_transmis_ne_sert_qu_a_son_destinataire(self, client, monde):
        monde.invitation_b.empreinte_jeton = _empreinte("jeton-vole")
        monde.invitation_b.save()

        _client_de(client, monde.alice).post(reverse("foyers:invitation", args=["jeton-vole"]))

        assert not Adhesion.objects.filter(
            foyer=monde.foyer_b, utilisateur=monde.alice.utilisateur
        ).exists()

    def test_un_membre_retire_perd_l_acces_immediatement(self, client, monde):
        client = _client_de(client, monde.carl)
        assert client.get(reverse("foyers:membres")).status_code == 200

        monde.carl.delete()

        reponse = client.get(reverse("foyers:membres"))
        assert reponse.status_code == 302
        assert reponse["Location"] == reverse("foyers:liste")


def _empreinte(jeton: str) -> str:
    from apps.foyers.services import empreinte

    return empreinte(jeton)


class TestRoles:
    @pytest.mark.parametrize("role", [Role.LECTEUR, Role.MEMBRE])
    def test_inviter_est_reserve_aux_administrateurs(self, client, role):
        adhesion = FabriqueAdhesion(role=role)

        reponse = _client_de(client, adhesion).post(
            reverse("foyers:inviter"), {"email": "x@example.org", "role": Role.MEMBRE}
        )

        assert reponse.status_code == 403
        assert not Invitation.objects.exists()

    def test_un_lecteur_consulte_mais_ne_voit_pas_les_invitations(self, client):
        lecteur = FabriqueAdhesion(role=Role.LECTEUR)
        FabriqueInvitation(foyer=lecteur.foyer, email="secret@example.org")

        reponse = _client_de(client, lecteur).get(reverse("foyers:membres"))

        assert reponse.status_code == 200
        assert "secret@example.org" not in reponse.content.decode()

    def test_un_membre_ne_peut_pas_changer_un_role(self, client):
        membre = FabriqueAdhesion(role=Role.MEMBRE)
        cible = FabriqueAdhesion(foyer=membre.foyer, role=Role.MEMBRE)

        reponse = _client_de(client, membre).post(
            reverse("foyers:changer_role", args=[cible.pk]), {"role": Role.LECTEUR}
        )

        assert reponse.status_code == 403

    def test_un_administrateur_ne_retrograde_pas_un_proprietaire(self, client):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)
        proprietaire = FabriqueAdhesion(foyer=admin.foyer, role=Role.PROPRIETAIRE)

        _client_de(client, admin).post(
            reverse("foyers:changer_role", args=[proprietaire.pk]), {"role": Role.MEMBRE}
        )

        proprietaire.refresh_from_db()
        assert proprietaire.role == Role.PROPRIETAIRE

    def test_le_dernier_proprietaire_ne_peut_pas_quitter(self, client):
        proprietaire = FabriqueAdhesion(role=Role.PROPRIETAIRE)

        _client_de(client, proprietaire).post(
            reverse("foyers:retirer_membre", args=[proprietaire.pk])
        )

        assert Adhesion.objects.filter(pk=proprietaire.pk).exists()

    def test_un_lecteur_peut_quitter_le_foyer(self, client):
        lecteur = FabriqueAdhesion(role=Role.LECTEUR)

        reponse = _client_de(client, lecteur).post(
            reverse("foyers:retirer_membre", args=[lecteur.pk])
        )

        assert reponse["Location"] == reverse("foyers:liste")
        assert not Adhesion.objects.filter(pk=lecteur.pk).exists()


class TestParcours:
    def test_sans_foyer_on_arrive_sur_ses_finances(self, client):
        alice = FabriqueUtilisateur()
        client.force_login(alice)

        reponse = client.get(reverse("accueil"))

        assert reponse.status_code == 200
        assert reponse.context["adhesion_espace"].foyer.personne == alice
        assert reponse.context["adhesion_foyer"] is None

    def test_creer_un_foyer_l_ouvre_aussitot(self, client):
        alice = FabriqueUtilisateur()
        client.force_login(alice)

        reponse = client.post(reverse("foyers:creer"), {"nom": "Maison"}, follow=True)

        foyer = Foyer.objects.get(personne__isnull=True)
        assert client.session[CLE_SESSION_FOYER] == foyer.pk
        assert reponse.context["adhesion_foyer"].foyer == foyer

    def test_le_foyer_principal_s_ouvre_par_defaut(self, client):
        alice = FabriqueUtilisateur()
        FabriqueAdhesion(utilisateur=alice, foyer__nom="Annexe")
        principale = FabriqueAdhesion(utilisateur=alice, foyer__nom="Zoé", est_principal=True)
        client.force_login(alice)

        reponse = client.get(reverse("accueil"))

        assert reponse.context["adhesion_foyer"] == principale

    def test_changer_de_foyer_courant_et_de_foyer_principal(self, client):
        alice = FabriqueUtilisateur()
        principale = FabriqueAdhesion(utilisateur=alice, est_principal=True)
        annexe = FabriqueAdhesion(utilisateur=alice)
        client.force_login(alice)

        client.post(reverse("foyers:activer", args=[annexe.foyer_id]))
        assert client.get(reverse("accueil")).context["adhesion_foyer"] == annexe

        client.post(reverse("foyers:principal", args=[annexe.foyer_id]))
        principale.refresh_from_db()
        annexe.refresh_from_db()
        assert annexe.est_principal and not principale.est_principal

    def test_invitation_de_bout_en_bout(self, client):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)
        dora = FabriqueUtilisateur(email="dora@example.org")

        _client_de(client, admin).post(
            reverse("foyers:inviter"), {"email": "Dora@example.org", "role": Role.LECTEUR}
        )
        lien = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        assert mail.outbox[0].to == ["dora@example.org"]

        client.force_login(dora)
        assert "Rejoindre le foyer" in client.get(lien).content.decode()
        client.post(lien)

        adhesion = Adhesion.objects.get(utilisateur=dora, foyer__personne__isnull=True)
        assert (adhesion.foyer, adhesion.role) == (admin.foyer, Role.LECTEUR)
        assert client.session[CLE_SESSION_FOYER] == admin.foyer_id

    def test_un_nouveau_venu_s_inscrit_depuis_le_lien_et_y_revient(self, client):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)
        _client_de(client, admin).post(
            reverse("foyers:inviter"), {"email": "eli@example.org", "role": Role.MEMBRE}
        )
        lien = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        chemin = lien.removeprefix("http://testserver")
        client.logout()

        connexion = client.get(lien, follow=True)
        assert f"?next={chemin}" in connexion.content.decode()
        inscription = client.post(
            f"{reverse('utilisateurs:inscription')}?next={chemin}",
            {
                "first_name": "Eli",
                "email": "eli@example.org",
                "password1": MOT_DE_PASSE,
                "password2": MOT_DE_PASSE,
                "next": chemin,
            },
        )
        assert inscription.url == chemin
        client.post(chemin)

        assert Adhesion.objects.filter(foyer=admin.foyer, utilisateur__email="eli@example.org")

    def test_le_lien_transfere_a_un_autre_compte_ne_sert_a_rien(self, client):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)
        _client_de(client, admin).post(
            reverse("foyers:inviter"), {"email": "dora@example.org", "role": Role.MEMBRE}
        )
        lien = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        client.force_login(FabriqueUtilisateur(email="eve@example.org"))

        assert "destinée à dora@example.org" in client.get(lien).content.decode()
        client.post(lien)

        assert not Adhesion.objects.filter(foyer=admin.foyer, utilisateur__email="eve@example.org")

    def test_seul_un_proprietaire_se_voit_proposer_le_role_proprietaire(self, client):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR, est_principal=True)
        FabriqueAdhesion(foyer=admin.foyer, role=Role.PROPRIETAIRE)
        proprietaire = FabriqueAdhesion(foyer=admin.foyer, role=Role.PROPRIETAIRE)

        page_admin = _client_de(client, admin).get(reverse("foyers:membres")).context
        page_proprietaire = _client_de(client, proprietaire).get(reverse("foyers:membres")).context

        assert Role.PROPRIETAIRE not in dict(page_admin["roles"])
        assert Role.PROPRIETAIRE not in dict(
            page_admin["formulaire_invitation"].fields["role"].choices
        )
        assert not [m for m in page_admin["membres"] if m.role == Role.PROPRIETAIRE and m.gerable]
        assert Role.PROPRIETAIRE in dict(
            page_proprietaire["formulaire_invitation"].fields["role"].choices
        )

    def test_inviter_sa_conjointe_comme_coproprietaire(self, client):
        moi = FabriqueAdhesion(role=Role.PROPRIETAIRE, est_principal=True)

        _client_de(client, moi).post(
            reverse("foyers:inviter"), {"email": "conjointe@example.org", "role": Role.PROPRIETAIRE}
        )

        assert Invitation.objects.get(email="conjointe@example.org").role == Role.PROPRIETAIRE

    def test_revoquer_une_invitation(self, client):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)
        invitation = FabriqueInvitation(foyer=admin.foyer)

        _client_de(client, admin).post(reverse("foyers:revoquer_invitation", args=[invitation.pk]))

        invitation.refresh_from_db()
        assert not invitation.est_en_attente

    def test_inviter_une_adresse_invalide_ne_cree_rien(self, client):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)

        _client_de(client, admin).post(
            reverse("foyers:inviter"), {"email": "pas-une-adresse", "role": Role.MEMBRE}
        )

        assert not Invitation.objects.exists()
        assert mail.outbox == []
