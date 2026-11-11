"""Finances personnelles et foyers partagés (ADR 0006).

Chacun a son espace (comptes, opérations, crédits). Dans un foyer, les écrans réunissent les
finances de tous ses membres, classées avec les catégories communes du foyer.
"""

from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.banque.models import Categorie, Compte, Operation
from apps.banque.tests.fabriques import FabriqueCompte, FabriqueOperation, FabriqueSousCategorie
from apps.budget.services.tableau import tableau_mensuel
from apps.foyers.espaces import acces_aux_espaces, espace_personnel
from apps.foyers.middleware import CLE_SESSION_FOYER
from apps.foyers.models import Adhesion, Foyer, Role
from apps.foyers.services import creer_foyer
from apps.socle.perimetre import Perimetre
from apps.utilisateurs.tests.fabriques import FabriqueUtilisateur

from .fabriques import FabriqueAdhesion, acces_a, espace_de

pytestmark = pytest.mark.django_db


def _comptes_affiches(client) -> set[str]:
    return {compte.nom for compte in client.get(reverse("banque:comptes")).context["comptes"]}


def _perimetre_de(adhesion: Adhesion) -> Perimetre:
    espaces = acces_aux_espaces(adhesion.utilisateur, adhesion.foyer)
    return Perimetre(tuple(a.foyer for a in espaces), adhesion.foyer)


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


class TestFoyerReuni:
    def test_les_ecrans_reunissent_les_comptes_de_tous_les_membres(self, client):
        dorian = espace_de(FabriqueUtilisateur(first_name="Dorian"))
        FabriqueCompte(foyer=dorian.foyer, nom="Courant SG")
        alexandra = acces_a(dorian)
        FabriqueCompte(foyer=espace_de(alexandra.utilisateur).foyer, nom="Bourso")
        client.force_login(alexandra.utilisateur)

        page = client.get(reverse("banque:comptes"))

        assert {c.nom for c in page.context["comptes"]} == {"Courant SG", "Bourso"}
        assert page.context["plusieurs_titulaires"]
        assert ">Dorian<" in page.content.decode()  # le titulaire est indiqué

    def test_un_membre_modifie_le_compte_d_un_autre(self, client):
        dorian = espace_de()
        compte = FabriqueCompte(foyer=dorian.foyer, nom="Ancien nom")
        client.force_login(acces_a(dorian, Role.MEMBRE).utilisateur)

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
        assert (compte.nom, compte.foyer) == ("Courant SG", dorian.foyer)

    def test_une_operation_sur_le_compte_d_un_autre_reste_dans_son_espace(self, client):
        dorian = espace_de()
        compte = FabriqueCompte(foyer=dorian.foyer, ouvert_le=date(2026, 1, 1))
        alexandra = acces_a(dorian)
        courses = FabriqueSousCategorie(parent__foyer=alexandra.foyer)  # catégorie du foyer
        client.force_login(alexandra.utilisateur)

        client.post(
            reverse("banque:ajouter_operation"),
            {
                "compte": compte.pk,
                "date": "2026-03-01",
                "libelle": "Courses",
                "sens": "depense",
                "montant": "50",
                "categorie": courses.pk,
            },
        )

        operation = Operation.objects.get()
        assert (operation.foyer, operation.categorie) == (dorian.foyer, courses)

    def test_virement_entre_les_comptes_de_deux_membres(self, client):
        dorian = espace_de()
        source = FabriqueCompte(foyer=dorian.foyer, ouvert_le=date(2026, 1, 1))
        alexandra = acces_a(dorian)
        destination = FabriqueCompte(foyer=espace_de(alexandra.utilisateur).foyer)
        client.force_login(alexandra.utilisateur)

        client.post(
            reverse("banque:ajouter_virement"),
            {
                "source": source.pk,
                "destination": destination.pk,
                "date": "2026-03-01",
                "montant": "100",
                "libelle": "Participation",
            },
        )

        debit, credit = Operation.objects.order_by("montant")
        assert (debit.foyer, credit.foyer) == (dorian.foyer, destination.foyer)
        assert debit.groupe_virement == credit.groupe_virement

    def test_un_lecteur_consulte_sans_modifier(self, client):
        dorian = espace_de()
        compte = FabriqueCompte(
            foyer=dorian.foyer, solde_initial=D("10"), ouvert_le=date(2026, 1, 1)
        )
        client.force_login(acces_a(dorian, Role.LECTEUR).utilisateur)

        assert compte.nom in _comptes_affiches(client)
        assert client.post(reverse("banque:archiver_compte", args=[compte.pk])).status_code == 403

    def test_seuls_les_membres_du_foyer_courant_sont_reunis(self, client):
        dorian = espace_de()
        FabriqueCompte(foyer=dorian.foyer, nom="Compte de Dorian")
        alexandra = acces_a(dorian)
        parents = FabriqueAdhesion(utilisateur=alexandra.utilisateur, foyer__nom="Parents")
        mere = FabriqueAdhesion(foyer=parents.foyer)
        FabriqueCompte(foyer=espace_de(mere.utilisateur).foyer, nom="Compte de la mère")
        client.force_login(alexandra.utilisateur)

        dans_le_couple = _comptes_affiches(client)
        session = client.session
        session[CLE_SESSION_FOYER] = parents.foyer_id
        session.save()
        chez_les_parents = _comptes_affiches(client)

        assert dans_le_couple == {"Compte de Dorian"}
        assert chez_les_parents == {"Compte de la mère"}


def _membre_d_un_foyer() -> Adhesion:
    """Quelqu'un qui partage un foyer avec un proche : les écrans réunissent plusieurs
    espaces pour lui, c'est donc là qu'une fuite vers l'espace d'un inconnu se produirait."""
    return acces_a(espace_de())


class TestIsolation:
    def test_les_comptes_d_un_inconnu_n_apparaissent_pas(self, client):
        compte = FabriqueCompte(foyer=espace_de().foyer, nom="Compte secret")
        client.force_login(_membre_d_un_foyer().utilisateur)

        assert "Compte secret" not in _comptes_affiches(client)
        assert client.get(reverse("banque:compte", args=[compte.pk])).status_code == 404
        assert "secret" not in client.get(reverse("banque:operations")).content.decode()

    def test_une_session_falsifiee_ne_donne_pas_un_autre_foyer(self, client):
        etranger = FabriqueAdhesion()
        FabriqueCompte(foyer=espace_de(etranger.utilisateur).foyer, nom="Compte secret")
        alice = _membre_d_un_foyer()
        client.force_login(alice.utilisateur)
        session = client.session
        session[CLE_SESSION_FOYER] = etranger.foyer_id
        session.save()

        reponse = client.get(reverse("banque:comptes"))

        assert reponse.context["adhesion_foyer"] == alice
        assert "secret" not in reponse.content.decode()

    def test_un_membre_retire_perd_aussitot_l_acces(self, client):
        dorian = espace_de()
        FabriqueCompte(foyer=dorian.foyer, nom="Compte de Dorian")
        ex = acces_a(dorian)
        client.force_login(ex.utilisateur)
        assert "Compte de Dorian" in _comptes_affiches(client)

        ex.delete()

        assert "Compte de Dorian" not in _comptes_affiches(client)

    def test_impossible_d_ecrire_sur_le_compte_d_un_inconnu(self, client):
        compte = FabriqueCompte(foyer=espace_de().foyer, ouvert_le=date(2026, 1, 1))
        client.force_login(_membre_d_un_foyer().utilisateur)

        reponse = client.post(
            reverse("banque:ajouter_operation"),
            {
                "compte": compte.pk,
                "date": "2026-03-01",
                "libelle": "x",
                "sens": "depense",
                "montant": "1",
            },
        )

        assert reponse.status_code == 200 and not Operation.objects.exists()


class TestClassementCommun:
    def test_un_nouveau_foyer_part_des_categories_de_son_createur(self):
        dorian = FabriqueUtilisateur()
        espace = espace_personnel(dorian)

        foyer = creer_foyer(utilisateur=dorian, nom="Maison")

        noms = set(Categorie.objects.filter(foyer=foyer).values_list("nom", flat=True))
        assert noms and noms == set(
            Categorie.objects.filter(foyer=espace).values_list("nom", flat=True)
        )

    def test_dans_un_foyer_les_categories_sont_celles_du_foyer(self, client):
        alexandra = acces_a(espace_de())
        client.force_login(alexandra.utilisateur)

        client.post(reverse("banque:ajouter_categorie"), {"nom": "Animaux", "nature": "depense"})

        assert Categorie.objects.get(nom="Animaux").foyer == alexandra.foyer

    def test_le_budget_du_foyer_range_les_categories_de_chacun_par_nom(self):
        dorian = espace_de()
        alexandra = acces_a(dorian)
        courses_foyer = FabriqueSousCategorie(
            parent__foyer=alexandra.foyer, parent__nom="Alimentation", nom="Courses"
        )
        courses_dorian = FabriqueSousCategorie(
            parent__foyer=dorian.foyer, parent__nom="ALIMENTATION", nom="courses"
        )
        compte_dorian = FabriqueCompte(foyer=dorian.foyer)
        compte_alexandra = FabriqueCompte(foyer=espace_de(alexandra.utilisateur).foyer)
        FabriqueOperation(
            compte=compte_dorian, categorie=courses_dorian, montant=D("-30"), date=date(2026, 3, 2)
        )
        FabriqueOperation(
            compte=compte_alexandra,
            categorie=courses_foyer,
            montant=D("-20"),
            date=date(2026, 3, 3),
        )

        tableau = tableau_mensuel(_perimetre_de(alexandra), 2026, 3)

        alimentation = next(
            ligne for ligne in tableau.depenses if ligne.categorie.nom == "Alimentation"
        )
        assert alimentation.sous_lignes[0].realise == D("50")
        assert tableau.depenses_non_classees == 0

    def test_sans_equivalent_dans_le_foyer_l_operation_est_a_classer(self):
        dorian = espace_de()
        alexandra = acces_a(dorian)
        exotique = FabriqueSousCategorie(parent__foyer=dorian.foyer, nom="Exotique")
        FabriqueOperation(
            compte=FabriqueCompte(foyer=dorian.foyer),
            categorie=exotique,
            montant=D("-7"),
            date=date(2026, 3, 2),
        )

        tableau = tableau_mensuel(_perimetre_de(alexandra), 2026, 3)

        assert tableau.depenses_non_classees == D("7")
