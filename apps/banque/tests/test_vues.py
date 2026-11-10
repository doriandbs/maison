from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.banque.models import Categorie, Compte, Operation, ReleveSolde, TypeCompte
from apps.banque.services.operations import creer_virement
from apps.foyers.models import Role
from apps.foyers.tests.fabriques import FabriqueAdhesion

from .fabriques import (
    FabriqueCategorie,
    FabriqueCompte,
    FabriqueOperation,
    FabriqueReleveSolde,
    FabriqueSousCategorie,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(client):
    """Membre du foyer A, connectée."""
    adhesion = FabriqueAdhesion(role=Role.MEMBRE, est_principal=True)
    client.force_login(adhesion.utilisateur)
    return adhesion


@pytest.fixture
def foyer_b():
    """Données d'un autre foyer, qu'Alice ne doit jamais atteindre."""
    compte = FabriqueCompte(nom="Compte secret", type=TypeCompte.PEA)
    sous_categorie = FabriqueSousCategorie(parent__foyer=compte.foyer, nom="Catégorie secrète")
    operation = FabriqueOperation(compte=compte, libelle="Opération secrète")
    releve = FabriqueReleveSolde(compte=compte)
    return SimpleNamespace(
        foyer=compte.foyer,
        compte=compte,
        sous_categorie=sous_categorie,
        operation=operation,
        releve=releve,
    )


ROUTES_SUR_UN_OBJET = [
    ("banque:compte", "compte"),
    ("banque:modifier_compte", "compte"),
    ("banque:archiver_compte", "compte"),
    ("banque:ajouter_releve", "compte"),
    ("banque:supprimer_releve", "releve"),
    ("banque:modifier_operation", "operation"),
    ("banque:supprimer_operation", "operation"),
    ("banque:modifier_categorie", "sous_categorie"),
    ("banque:archiver_categorie", "sous_categorie"),
]


class TestIsolationEntreFoyers:
    @pytest.mark.parametrize(("route", "objet"), ROUTES_SUR_UN_OBJET)
    def test_l_objet_d_un_autre_foyer_est_introuvable(self, client, alice, foyer_b, route, objet):
        url = reverse(route, args=[getattr(foyer_b, objet).pk])
        donnees = {"date": "2026-04-30", "montant": "1", "nom": "piraté", "libelle": "piraté"}

        # 405 : méthode non prévue par la vue (détail en GET seul, action en POST seul).
        codes = {client.get(url).status_code, client.post(url, donnees).status_code}

        assert codes <= {404, 405}
        assert 404 in codes

    def test_rien_n_a_ete_modifie_dans_l_autre_foyer(self, client, alice, foyer_b):
        for route, objet in ROUTES_SUR_UN_OBJET:
            client.post(reverse(route, args=[getattr(foyer_b, objet).pk]), {"nom": "piraté"})

        foyer_b.compte.refresh_from_db()
        foyer_b.sous_categorie.refresh_from_db()
        assert foyer_b.compte.nom == "Compte secret" and not foyer_b.compte.est_archive
        assert not foyer_b.sous_categorie.est_archivee
        assert Operation.objects.filter(pk=foyer_b.operation.pk).exists()
        assert ReleveSolde.objects.filter(pk=foyer_b.releve.pk).count() == 1
        assert ReleveSolde.objects.count() == 1

    @pytest.mark.parametrize("route", ["banque:comptes", "banque:operations", "banque:categories"])
    def test_les_listes_ne_montrent_que_le_foyer_courant(self, client, alice, foyer_b, route):
        contenu = client.get(reverse(route)).content.decode()

        assert "secr" not in contenu

    def test_filtrer_les_operations_sur_le_compte_d_autrui_ne_montre_rien(
        self, client, alice, foyer_b
    ):
        reponse = client.get(reverse("banque:operations"), {"compte": foyer_b.compte.pk})

        assert "Opération secrète" not in reponse.content.decode()

    def test_creer_une_operation_sur_le_compte_d_autrui_est_refuse(self, client, alice, foyer_b):
        reponse = client.post(
            reverse("banque:ajouter_operation"),
            {
                "compte": foyer_b.compte.pk,
                "date": "2026-03-15",
                "libelle": "Intrusion",
                "sens": "depense",
                "montant": "10",
            },
        )

        assert reponse.status_code == 200
        assert not Operation.objects.filter(libelle="Intrusion").exists()

    def test_virer_vers_le_compte_d_autrui_est_refuse(self, client, alice, foyer_b):
        source = FabriqueCompte(foyer=alice.foyer)

        reponse = client.post(
            reverse("banque:ajouter_virement"),
            {
                "source": source.pk,
                "destination": foyer_b.compte.pk,
                "date": "2026-03-15",
                "montant": "10",
                "libelle": "Fuite",
            },
        )

        assert reponse.status_code == 200
        assert not Operation.objects.filter(libelle="Fuite").exists()

    def test_pre_remplir_avec_l_identifiant_d_autrui_ne_revele_rien(self, client, alice, foyer_b):
        reponse = client.get(reverse("banque:ajouter_operation"), {"compte": foyer_b.compte.pk})

        assert "Compte secret" not in reponse.content.decode()


ROUTES_D_ECRITURE = [
    ("banque:ajouter_compte", None),
    ("banque:modifier_compte", "compte"),
    ("banque:archiver_compte", "compte"),
    ("banque:ajouter_releve", "compte"),
    ("banque:ajouter_operation", None),
    ("banque:modifier_operation", "operation"),
    ("banque:supprimer_operation", "operation"),
    ("banque:ajouter_virement", None),
    ("banque:ajouter_categorie", None),
    ("banque:modifier_categorie", "sous_categorie"),
    ("banque:archiver_categorie", "sous_categorie"),
]


class TestLectureSeule:
    @pytest.mark.parametrize(("route", "objet"), ROUTES_D_ECRITURE)
    def test_un_lecteur_ne_peut_rien_modifier(self, client, route, objet):
        lecteur = FabriqueAdhesion(role=Role.LECTEUR)
        compte = FabriqueCompte(foyer=lecteur.foyer)
        objets = {
            "compte": compte,
            "operation": FabriqueOperation(compte=compte),
            "sous_categorie": FabriqueSousCategorie(parent__foyer=lecteur.foyer),
        }
        client.force_login(lecteur.utilisateur)
        arguments = [objets[objet].pk] if objet else []

        reponse = client.post(reverse(route, args=arguments), {})

        assert reponse.status_code == 403

    def test_un_lecteur_consulte_sans_voir_les_boutons_d_action(self, client):
        lecteur = FabriqueAdhesion(role=Role.LECTEUR)
        FabriqueOperation(compte=FabriqueCompte(foyer=lecteur.foyer, nom="Courant"))
        client.force_login(lecteur.utilisateur)

        comptes = client.get(reverse("banque:comptes")).content.decode()
        operations = client.get(reverse("banque:operations")).content.decode()

        assert "Courant" in comptes and "Ajouter un compte" not in comptes
        assert "Supprimer" not in operations


class TestComptes:
    def test_creer_un_compte_puis_voir_son_solde(self, client, alice):
        client.post(
            reverse("banque:ajouter_compte"),
            {
                "nom": "Courant",
                "type": "courant",
                "etablissement": "Banque",
                "titulaires": [alice.pk],
                "solde_initial": "1500.00",
                "ouvert_le": "2026-01-01",
            },
        )
        compte = Compte.objects.get()
        FabriqueOperation(compte=compte, montant=Decimal("-265.50"))

        reponse = client.get(reverse("banque:comptes"))

        assert (compte.foyer, list(compte.titulaires.all())) == (alice.foyer, [alice])
        assert reponse.context["total"] == Decimal("1234.50")
        assert "1 234,50 €" in reponse.content.decode()

    def test_comptes_affiches_par_etablissement(self, client, alice):
        FabriqueCompte(foyer=alice.foyer, nom="Joint", etablissement="Crédit Mutuel")
        FabriqueCompte(foyer=alice.foyer, nom="Livret A", etablissement="crédit mutuel")
        FabriqueCompte(foyer=alice.foyer, nom="PEA", etablissement="Boursorama")

        reponse = client.get(reverse("banque:comptes"))
        groupes = reponse.context["groupes"]

        assert [(g.nom, len(g.lignes)) for g in groupes] == [
            ("Boursorama", 1),
            ("Crédit Mutuel", 2),
        ]
        assert "2 comptes" in reponse.content.decode()

    def test_le_total_ignore_les_comptes_archives(self, client, alice):
        FabriqueCompte(foyer=alice.foyer, solde_initial=Decimal("100.00"))
        FabriqueCompte(
            foyer=alice.foyer, solde_initial=Decimal("900.00"), archive_le=timezone.now()
        )

        reponse = client.get(reverse("banque:comptes"))

        assert reponse.context["total"] == Decimal("100.00")
        assert len(reponse.context["comptes_archives"]) == 1

    def test_archiver_conserve_l_historique_puis_desarchiver(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer)
        FabriqueOperation(compte=compte)

        client.post(reverse("banque:archiver_compte", args=[compte.pk]))
        compte.refresh_from_db()
        assert compte.est_archive and compte.operations.count() == 1

        client.post(reverse("banque:archiver_compte", args=[compte.pk]))
        compte.refresh_from_db()
        assert not compte.est_archive

    def test_modifier_un_compte(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer, nom="Ancien")

        client.post(
            reverse("banque:modifier_compte", args=[compte.pk]),
            {"nom": "Nouveau", "type": "livret", "solde_initial": "5", "ouvert_le": "2026-01-01"},
        )

        compte.refresh_from_db()
        assert (compte.nom, compte.type) == ("Nouveau", "livret")

    def test_releves_d_un_compte_valorise(self, client, alice):
        pea = FabriqueCompte(foyer=alice.foyer, type=TypeCompte.PEA)

        client.post(
            reverse("banque:ajouter_releve", args=[pea.pk]),
            {"date": "2026-03-31", "montant": "5450.00"},
        )
        reponse = client.get(reverse("banque:compte", args=[pea.pk]))
        assert reponse.context["solde"] == Decimal("5450.00")

        client.post(reverse("banque:supprimer_releve", args=[pea.releves.get().pk]))
        assert not pea.releves.exists()

    def test_releve_invalide_ignore(self, client, alice):
        pea = FabriqueCompte(foyer=alice.foyer, type=TypeCompte.PEA)

        client.post(reverse("banque:ajouter_releve", args=[pea.pk]), {"date": "", "montant": "x"})

        assert not pea.releves.exists()

    def test_un_compte_ordinaire_ne_propose_pas_de_releves(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer)

        reponse = client.get(reverse("banque:compte", args=[compte.pk]))

        assert "formulaire_releve" not in reponse.context


class TestOperations:
    def test_ajouter_une_operation(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer)
        categorie = FabriqueSousCategorie(parent__foyer=alice.foyer)

        client.post(
            reverse("banque:ajouter_operation"),
            {
                "compte": compte.pk,
                "date": "2026-03-15",
                "libelle": "EDF",
                "sens": "depense",
                "montant": "92",
                "categorie": categorie.pk,
            },
        )

        operation = Operation.objects.get()
        assert (operation.montant, operation.categorie) == (Decimal("-92.00"), categorie)
        assert (operation.foyer, operation.cree_par) == (alice.foyer, alice.utilisateur)

    def test_modifier_une_operation(self, client, alice):
        operation = FabriqueOperation(compte=FabriqueCompte(foyer=alice.foyer))

        client.post(
            reverse("banque:modifier_operation", args=[operation.pk]),
            {
                "compte": operation.compte_id,
                "date": "2026-04-01",
                "libelle": "Corrigée",
                "sens": "recette",
                "montant": "15",
            },
        )

        operation.refresh_from_db()
        assert (operation.libelle, operation.montant) == ("Corrigée", Decimal("15.00"))
        assert operation.date == date(2026, 4, 1)

    def test_supprimer_demande_confirmation(self, client, alice):
        operation = FabriqueOperation(compte=FabriqueCompte(foyer=alice.foyer))
        url = reverse("banque:supprimer_operation", args=[operation.pk])

        assert client.get(url).status_code == 200
        assert Operation.objects.exists()
        client.post(url)
        assert not Operation.objects.exists()

    def test_virement_interne(self, client, alice):
        courant = FabriqueCompte(foyer=alice.foyer, solde_initial=Decimal("500.00"))
        livret = FabriqueCompte(foyer=alice.foyer)

        client.post(
            reverse("banque:ajouter_virement"),
            {
                "source": courant.pk,
                "destination": livret.pk,
                "date": "2026-03-01",
                "montant": "200",
                "libelle": "Épargne du mois",
            },
        )

        debit, credit = Operation.objects.order_by("montant")
        assert (debit.compte, credit.compte) == (courant, livret)
        assert debit.groupe_virement == credit.groupe_virement
        assert debit.cree_par == alice.utilisateur

    def test_un_virement_ne_se_modifie_pas_mais_se_supprime_en_entier(self, client, alice):
        courant = FabriqueCompte(foyer=alice.foyer)
        livret = FabriqueCompte(foyer=alice.foyer)
        debit, _credit = creer_virement(
            source=courant,
            destination=livret,
            date_virement=date(2026, 3, 1),
            montant=Decimal("50"),
            libelle="Virement",
        )

        assert client.get(reverse("banque:modifier_operation", args=[debit.pk])).status_code == 404
        client.post(reverse("banque:supprimer_operation", args=[debit.pk]))
        assert not Operation.objects.exists()

    def test_filtres_par_compte_et_par_mois(self, client, alice):
        courant = FabriqueCompte(foyer=alice.foyer)
        livret = FabriqueCompte(foyer=alice.foyer)
        mars = FabriqueOperation(compte=courant, date=date(2026, 3, 10))
        FabriqueOperation(compte=courant, date=date(2026, 4, 10))
        FabriqueOperation(compte=livret, date=date(2026, 3, 10))

        reponse = client.get(
            reverse("banque:operations"), {"compte": courant.pk, "mois": "2026-03"}
        )

        assert list(reponse.context["operations"]) == [mars]

    def test_filtre_invalide_ignore(self, client, alice):
        operation = FabriqueOperation(compte=FabriqueCompte(foyer=alice.foyer))

        reponse = client.get(reverse("banque:operations"), {"mois": "n'importe quoi"})

        assert list(reponse.context["operations"]) == [operation]

    def test_pagination(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer)
        FabriqueOperation.create_batch(51, compte=compte)

        reponse = client.get(reverse("banque:operations"), {"compte": compte.pk, "page": 2})

        assert len(reponse.context["operations"]) == 1
        assert f"compte={compte.pk}&page=1" in reponse.content.decode().replace("&amp;", "&")


class TestCategories:
    def test_liste_en_arbre(self, client, alice):
        sous_categorie = FabriqueSousCategorie(parent__foyer=alice.foyer, nom="Électricité")

        reponse = client.get(reverse("banque:categories"))

        assert list(reponse.context["categories"]) == [sous_categorie.parent]
        assert "Électricité" in reponse.content.decode()

    def test_ajouter_une_sous_categorie(self, client, alice):
        parente = FabriqueCategorie(foyer=alice.foyer, nature="revenu")

        client.post(
            reverse("banque:ajouter_categorie"),
            {"nom": "Loyers perçus", "parent": parente.pk, "nature": "depense"},
        )

        categorie = Categorie.objects.get(nom="Loyers perçus")
        assert (categorie.foyer, categorie.parent, categorie.nature) == (
            alice.foyer,
            parente,
            "revenu",
        )

    def test_archiver_une_categorie(self, client, alice):
        sous_categorie = FabriqueSousCategorie(parent__foyer=alice.foyer)

        client.post(reverse("banque:archiver_categorie", args=[sous_categorie.pk]))

        sous_categorie.refresh_from_db()
        assert sous_categorie.est_archivee
