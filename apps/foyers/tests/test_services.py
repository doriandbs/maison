from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.foyers import services
from apps.foyers.models import Adhesion, Invitation, Role
from apps.foyers.services import ErreurFoyer
from apps.utilisateurs.tests.fabriques import FabriqueUtilisateur

from .fabriques import FabriqueAdhesion, FabriqueFoyer, FabriqueInvitation

pytestmark = pytest.mark.django_db


class TestCreerFoyer:
    def test_le_createur_devient_proprietaire_et_le_premier_foyer_est_principal(self):
        alice = FabriqueUtilisateur()

        foyer = services.creer_foyer(utilisateur=alice, nom="Maison")

        adhesion = Adhesion.objects.get(foyer=foyer)
        assert (adhesion.utilisateur, adhesion.role, adhesion.est_principal) == (
            alice,
            Role.PROPRIETAIRE,
            True,
        )

    def test_les_foyers_suivants_sont_annexes(self):
        alice = FabriqueUtilisateur()
        services.creer_foyer(utilisateur=alice, nom="Maison")

        location = services.creer_foyer(utilisateur=alice, nom="Location")

        assert not Adhesion.objects.get(foyer=location).est_principal


class TestFoyerPrincipal:
    def test_un_seul_foyer_principal_a_la_fois(self):
        alice = FabriqueUtilisateur()
        ancienne = FabriqueAdhesion(utilisateur=alice, est_principal=True)
        nouvelle = FabriqueAdhesion(utilisateur=alice)

        services.definir_foyer_principal(nouvelle)

        ancienne.refresh_from_db()
        assert nouvelle.est_principal and not ancienne.est_principal

    def test_la_base_refuse_deux_foyers_principaux(self):
        alice = FabriqueUtilisateur()
        FabriqueAdhesion(utilisateur=alice, est_principal=True)

        with pytest.raises(IntegrityError):
            FabriqueAdhesion(utilisateur=alice, est_principal=True)


class TestInviter:
    def test_cree_une_invitation_sans_stocker_le_jeton(self):
        alice = FabriqueAdhesion(role=Role.ADMINISTRATEUR)

        invitation, jeton = services.inviter(
            foyer=alice.foyer,
            email=" Bob@Example.org ",
            role=Role.LECTEUR,
            invite_par=alice.utilisateur,
        )

        assert invitation.email == "bob@example.org"
        assert invitation.empreinte_jeton == services.empreinte(jeton)
        assert jeton not in invitation.empreinte_jeton
        assert invitation.expire_le > timezone.now() + timedelta(days=6)

    def test_un_administrateur_ne_peut_pas_inviter_un_proprietaire(self):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)

        with pytest.raises(ErreurFoyer):
            services.inviter(
                foyer=admin.foyer,
                email="bob@example.org",
                role=Role.PROPRIETAIRE,
                invite_par=admin.utilisateur,
            )

    def test_un_proprietaire_peut_inviter_un_coproprietaire(self):
        proprietaire = FabriqueAdhesion(role=Role.PROPRIETAIRE)
        bob = FabriqueUtilisateur(email="bob@example.org")

        invitation, _ = services.inviter(
            foyer=proprietaire.foyer,
            email="bob@example.org",
            role=Role.PROPRIETAIRE,
            invite_par=proprietaire.utilisateur,
        )
        services.accepter_invitation(invitation=invitation, utilisateur=bob)

        roles = set(Adhesion.objects.du_foyer(proprietaire.foyer).values_list("role", flat=True))
        assert roles == {Role.PROPRIETAIRE}

    @pytest.mark.parametrize("role", [None, Role.MEMBRE])
    def test_seul_un_administrateur_du_foyer_invite(self, role):
        foyer = FabriqueFoyer()
        invitant = FabriqueAdhesion(foyer=foyer, role=role).utilisateur if role else None

        with pytest.raises(ErreurFoyer):
            services.inviter(
                foyer=foyer,
                email="bob@example.org",
                role=Role.LECTEUR,
                invite_par=invitant or FabriqueUtilisateur(),
            )

    def test_refuse_une_personne_deja_membre(self):
        adhesion = FabriqueAdhesion()
        admin = FabriqueAdhesion(foyer=adhesion.foyer, role=Role.ADMINISTRATEUR)

        with pytest.raises(ErreurFoyer):
            services.inviter(
                foyer=adhesion.foyer,
                email=adhesion.utilisateur.email,
                role=Role.MEMBRE,
                invite_par=admin.utilisateur,
            )

    def test_une_nouvelle_invitation_revoque_la_precedente(self):
        ancienne = FabriqueInvitation(email="bob@example.org")
        admin = FabriqueAdhesion(foyer=ancienne.foyer, role=Role.ADMINISTRATEUR)

        services.inviter(
            foyer=ancienne.foyer,
            email="bob@example.org",
            role=Role.MEMBRE,
            invite_par=admin.utilisateur,
        )

        ancienne.refresh_from_db()
        assert ancienne.revoquee_le is not None
        assert Invitation.objects.du_foyer(ancienne.foyer).en_attente().count() == 1


class TestAccepterInvitation:
    def test_cree_l_adhesion_avec_le_role_prevu(self):
        bob = FabriqueUtilisateur(email="bob@example.org")
        invitation = FabriqueInvitation(email="bob@example.org", role=Role.LECTEUR)

        adhesion = services.accepter_invitation(invitation=invitation, utilisateur=bob)

        invitation.refresh_from_db()
        assert (adhesion.foyer, adhesion.role) == (invitation.foyer, Role.LECTEUR)
        assert adhesion.est_principal
        assert invitation.acceptee_le is not None

    def test_ne_remplace_pas_le_foyer_principal_existant(self):
        bob = FabriqueUtilisateur(email="bob@example.org")
        FabriqueAdhesion(utilisateur=bob, est_principal=True)

        adhesion = services.accepter_invitation(
            invitation=FabriqueInvitation(email="bob@example.org"), utilisateur=bob
        )

        assert not adhesion.est_principal

    @pytest.mark.parametrize(
        "etat",
        [
            {"expire_le": timezone.now() - timedelta(minutes=1)},
            {"revoquee_le": timezone.now()},
            {"acceptee_le": timezone.now()},
        ],
    )
    def test_refuse_une_invitation_qui_n_est_plus_en_attente(self, etat):
        bob = FabriqueUtilisateur(email="bob@example.org")
        invitation = FabriqueInvitation(email="bob@example.org", **etat)

        with pytest.raises(ErreurFoyer):
            services.accepter_invitation(invitation=invitation, utilisateur=bob)
        assert not Adhesion.objects.filter(utilisateur=bob).exists()

    def test_refuse_un_autre_destinataire(self):
        eve = FabriqueUtilisateur(email="eve@example.org")
        invitation = FabriqueInvitation(email="bob@example.org")

        with pytest.raises(ErreurFoyer):
            services.accepter_invitation(invitation=invitation, utilisateur=eve)
        assert not Adhesion.objects.filter(utilisateur=eve).exists()


class TestChangerRole:
    def test_un_administrateur_gere_les_roles_ordinaires(self):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)
        cible = FabriqueAdhesion(foyer=admin.foyer, role=Role.MEMBRE)

        services.changer_role(adhesion=cible, role=Role.LECTEUR, par=admin)

        cible.refresh_from_db()
        assert cible.role == Role.LECTEUR

    @pytest.mark.parametrize("role_acteur", [Role.MEMBRE, Role.LECTEUR])
    def test_refuse_un_acteur_sans_droit_de_gestion(self, role_acteur):
        acteur = FabriqueAdhesion(role=role_acteur)
        cible = FabriqueAdhesion(foyer=acteur.foyer)

        with pytest.raises(ErreurFoyer):
            services.changer_role(adhesion=cible, role=Role.LECTEUR, par=acteur)

    def test_refuse_un_acteur_d_un_autre_foyer(self):
        proprietaire_ailleurs = FabriqueAdhesion(role=Role.PROPRIETAIRE)
        cible = FabriqueAdhesion()

        with pytest.raises(ErreurFoyer):
            services.changer_role(adhesion=cible, role=Role.LECTEUR, par=proprietaire_ailleurs)

    def test_un_administrateur_ne_peut_ni_nommer_ni_retrograder_un_proprietaire(self):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)
        proprietaire = FabriqueAdhesion(foyer=admin.foyer, role=Role.PROPRIETAIRE)
        membre = FabriqueAdhesion(foyer=admin.foyer)

        with pytest.raises(ErreurFoyer):
            services.changer_role(adhesion=proprietaire, role=Role.MEMBRE, par=admin)
        with pytest.raises(ErreurFoyer):
            services.changer_role(adhesion=membre, role=Role.PROPRIETAIRE, par=admin)

    def test_un_proprietaire_peut_en_nommer_un_autre(self):
        proprietaire = FabriqueAdhesion(role=Role.PROPRIETAIRE)
        membre = FabriqueAdhesion(foyer=proprietaire.foyer)

        services.changer_role(adhesion=membre, role=Role.PROPRIETAIRE, par=proprietaire)

        membre.refresh_from_db()
        assert membre.role == Role.PROPRIETAIRE

    def test_le_dernier_proprietaire_ne_peut_pas_etre_retrograde(self):
        proprietaire = FabriqueAdhesion(role=Role.PROPRIETAIRE)

        with pytest.raises(ErreurFoyer):
            services.changer_role(adhesion=proprietaire, role=Role.MEMBRE, par=proprietaire)

    def test_refuse_un_role_inconnu(self):
        proprietaire = FabriqueAdhesion(role=Role.PROPRIETAIRE)

        with pytest.raises(ErreurFoyer):
            services.changer_role(adhesion=proprietaire, role="dieu", par=proprietaire)


class TestRetirerMembre:
    def test_un_administrateur_retire_un_membre(self):
        admin = FabriqueAdhesion(role=Role.ADMINISTRATEUR)
        cible = FabriqueAdhesion(foyer=admin.foyer)

        services.retirer_membre(adhesion=cible, par=admin)

        assert not Adhesion.objects.filter(pk=cible.pk).exists()

    def test_un_membre_ne_peut_pas_en_retirer_un_autre(self):
        membre = FabriqueAdhesion()
        cible = FabriqueAdhesion(foyer=membre.foyer)

        with pytest.raises(ErreurFoyer):
            services.retirer_membre(adhesion=cible, par=membre)

    def test_un_lecteur_peut_quitter_le_foyer(self):
        lecteur = FabriqueAdhesion(role=Role.LECTEUR)

        services.retirer_membre(adhesion=lecteur, par=lecteur)

        assert not Adhesion.objects.filter(pk=lecteur.pk).exists()

    def test_le_dernier_proprietaire_ne_peut_pas_partir(self):
        proprietaire = FabriqueAdhesion(role=Role.PROPRIETAIRE)

        with pytest.raises(ErreurFoyer):
            services.retirer_membre(adhesion=proprietaire, par=proprietaire)

    def test_quitter_son_foyer_principal_en_designe_un_autre(self):
        alice = FabriqueUtilisateur()
        principale = FabriqueAdhesion(utilisateur=alice, est_principal=True)
        annexe = FabriqueAdhesion(utilisateur=alice)

        services.retirer_membre(adhesion=principale, par=principale)

        annexe.refresh_from_db()
        assert annexe.est_principal
