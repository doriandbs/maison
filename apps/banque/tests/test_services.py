from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.banque.models import Categorie, Nature, Operation, ReleveSolde, TypeCompte
from apps.banque.services.categories import (
    CATEGORIES_PAR_DEFAUT,
    basculer_archivage_categorie,
)
from apps.banque.services.operations import ErreurVirement, creer_virement, supprimer_operation
from apps.banque.services.regroupement import regrouper_par_etablissement
from apps.banque.services.soldes import enregistrer_releve, soldes_des_comptes
from apps.foyers.services import creer_foyer
from apps.foyers.tests.fabriques import FabriqueFoyer
from apps.socle.templatetags.formats import euros
from apps.utilisateurs.tests.fabriques import FabriqueUtilisateur

from .fabriques import (
    FabriqueCategorie,
    FabriqueCompte,
    FabriqueOperation,
    FabriqueReleveSolde,
    FabriqueSousCategorie,
)

pytestmark = pytest.mark.django_db

D = Decimal


class TestSoldes:
    def test_solde_initial_plus_operations(self):
        compte = FabriqueCompte(solde_initial=D("1000.00"))
        FabriqueOperation(compte=compte, montant=D("-120.50"))
        FabriqueOperation(compte=compte, montant=D("2000.00"))

        assert soldes_des_comptes(compte.foyer) == {compte.pk: D("2879.50")}

    def test_compte_sans_operation(self):
        compte = FabriqueCompte(solde_initial=D("42.00"))

        assert soldes_des_comptes(compte.foyer)[compte.pk] == D("42.00")

    def test_solde_a_une_date_passee(self):
        compte = FabriqueCompte(solde_initial=D("100.00"))
        FabriqueOperation(compte=compte, date=date(2026, 2, 10), montant=D("-30.00"))
        FabriqueOperation(compte=compte, date=date(2026, 3, 10), montant=D("-50.00"))

        assert soldes_des_comptes(compte.foyer, date(2026, 2, 28))[compte.pk] == D("70.00")
        assert soldes_des_comptes(compte.foyer, date(2026, 3, 10))[compte.pk] == D("20.00")

    def test_les_operations_des_autres_foyers_ne_comptent_pas(self):
        compte = FabriqueCompte(solde_initial=D("100.00"))
        FabriqueOperation(compte=FabriqueCompte(), montant=D("-999.00"))

        assert soldes_des_comptes(compte.foyer) == {compte.pk: D("100.00")}

    def test_compte_valorise_dernier_releve_fait_foi(self):
        pea = FabriqueCompte(type=TypeCompte.PEA, solde_initial=D("5000.00"))
        FabriqueOperation(compte=pea, date=date(2026, 2, 5), montant=D("200.00"))
        FabriqueReleveSolde(compte=pea, date=date(2026, 1, 31), montant=D("5100.00"))
        FabriqueReleveSolde(compte=pea, date=date(2026, 2, 28), montant=D("5450.00"))

        assert soldes_des_comptes(pea.foyer)[pea.pk] == D("5450.00")

    def test_compte_valorise_ajoute_les_operations_posterieures_au_releve(self):
        pea = FabriqueCompte(type=TypeCompte.PEA)
        FabriqueReleveSolde(compte=pea, date=date(2026, 2, 28), montant=D("5450.00"))
        FabriqueOperation(compte=pea, date=date(2026, 2, 28), montant=D("999.00"))
        FabriqueOperation(compte=pea, date=date(2026, 3, 5), montant=D("150.00"))

        assert soldes_des_comptes(pea.foyer)[pea.pk] == D("5600.00")

    def test_compte_valorise_sans_releve_se_comporte_comme_un_compte_ordinaire(self):
        pea = FabriqueCompte(type=TypeCompte.PEA, solde_initial=D("5000.00"))
        FabriqueOperation(compte=pea, montant=D("200.00"))

        assert soldes_des_comptes(pea.foyer)[pea.pk] == D("5200.00")

    def test_compte_valorise_a_une_date_anterieure_au_dernier_releve(self):
        pea = FabriqueCompte(type=TypeCompte.PEA)
        FabriqueReleveSolde(compte=pea, date=date(2026, 1, 31), montant=D("5100.00"))
        FabriqueReleveSolde(compte=pea, date=date(2026, 2, 28), montant=D("5450.00"))

        assert soldes_des_comptes(pea.foyer, date(2026, 2, 15))[pea.pk] == D("5100.00")

    def test_un_releve_est_ignore_sur_un_compte_ordinaire(self):
        courant = FabriqueCompte(solde_initial=D("10.00"))
        FabriqueReleveSolde(compte=courant, montant=D("777.00"))

        assert soldes_des_comptes(courant.foyer)[courant.pk] == D("10.00")

    def test_ressaisir_un_releve_le_meme_jour_le_corrige(self):
        pea = FabriqueCompte(type=TypeCompte.PEA)
        enregistrer_releve(compte=pea, date_releve=date(2026, 3, 31), montant=D("100.00"))
        enregistrer_releve(compte=pea, date_releve=date(2026, 3, 31), montant=D("120.00"))

        releve = ReleveSolde.objects.get()
        assert (releve.montant, releve.foyer) == (D("120.00"), pea.foyer)


class TestVirements:
    def test_cree_deux_operations_liees_de_somme_nulle(self):
        courant = FabriqueCompte(solde_initial=D("500.00"))
        livret = FabriqueCompte(foyer=courant.foyer)

        debit, credit = creer_virement(
            source=courant,
            destination=livret,
            date_virement=date(2026, 3, 1),
            montant=D("200.00"),
            libelle="Épargne",
        )

        assert (debit.compte, debit.montant) == (courant, D("-200.00"))
        assert (credit.compte, credit.montant) == (livret, D("200.00"))
        assert debit.groupe_virement == credit.groupe_virement is not None
        assert debit.est_virement and debit.categorie is None
        assert soldes_des_comptes(courant.foyer) == {
            courant.pk: D("300.00"),
            livret.pk: D("200.00"),
        }

    @pytest.mark.parametrize("montant", [D("0"), D("-5")])
    def test_refuse_un_montant_non_positif(self, montant):
        courant = FabriqueCompte()
        livret = FabriqueCompte(foyer=courant.foyer)

        with pytest.raises(ErreurVirement):
            creer_virement(
                source=courant,
                destination=livret,
                date_virement=date(2026, 3, 1),
                montant=montant,
                libelle="x",
            )

    def test_refuse_le_meme_compte(self):
        courant = FabriqueCompte()

        with pytest.raises(ErreurVirement):
            creer_virement(
                source=courant,
                destination=courant,
                date_virement=date(2026, 3, 1),
                montant=D("1"),
                libelle="x",
            )

    def test_refuse_un_virement_entre_deux_foyers(self):
        with pytest.raises(ErreurVirement):
            creer_virement(
                source=FabriqueCompte(),
                destination=FabriqueCompte(),
                date_virement=date(2026, 3, 1),
                montant=D("1"),
                libelle="x",
            )
        assert not Operation.objects.exists()

    def test_supprimer_une_jambe_supprime_le_virement_entier(self):
        courant = FabriqueCompte()
        livret = FabriqueCompte(foyer=courant.foyer)
        autre = FabriqueOperation(compte=courant)
        _debit, credit = creer_virement(
            source=courant,
            destination=livret,
            date_virement=date(2026, 3, 1),
            montant=D("200.00"),
            libelle="Épargne",
        )

        supprimer_operation(credit)

        assert list(Operation.objects.all()) == [autre]

    def test_supprimer_une_operation_ordinaire(self):
        operation = FabriqueOperation()
        autre = FabriqueOperation(compte=operation.compte)

        supprimer_operation(operation)

        assert list(Operation.objects.all()) == [autre]


class TestContraintesOperation:
    def test_montant_nul_refuse_par_la_base(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            FabriqueOperation(montant=D("0.00"))

    def test_un_virement_ne_porte_pas_de_categorie(self):
        sous_categorie = FabriqueSousCategorie()
        compte = FabriqueCompte(foyer=sous_categorie.foyer)

        with pytest.raises(IntegrityError), transaction.atomic():
            FabriqueOperation(
                compte=compte,
                categorie=sous_categorie,
                groupe_virement="6f1c0d3e-0000-4000-8000-000000000001",
            )

    def test_clean_refuse_un_compte_ou_une_categorie_d_un_autre_foyer(self):
        operation = FabriqueOperation.build(
            compte=FabriqueCompte(), foyer=FabriqueFoyer(), categorie=None
        )
        with pytest.raises(ValidationError):
            operation.clean()

        compte = FabriqueCompte()
        operation = FabriqueOperation.build(
            compte=compte, foyer=compte.foyer, categorie=FabriqueSousCategorie()
        )
        with pytest.raises(ValidationError):
            operation.clean()


class TestCategories:
    def test_un_nouveau_foyer_recoit_les_categories_par_defaut(self):
        foyer = creer_foyer(utilisateur=FabriqueUtilisateur(), nom="Maison")

        categories = Categorie.objects.du_foyer(foyer)
        parents = categories.filter(parent__isnull=True)
        attendu = sum(len(arbre) for arbre in CATEGORIES_PAR_DEFAUT.values())
        assert parents.count() == attendu
        assert categories.get(nom="Électricité").parent.nom == "Énergie"
        assert categories.get(nom="Salaire").nature == Nature.REVENU
        assert not categories.filter(nom__icontains="épargne").exists()
        assert all(parent.sous_categories.exists() for parent in parents)

    def test_une_sous_categorie_reprend_la_nature_de_sa_parente(self):
        revenus = FabriqueCategorie(nature=Nature.REVENU)
        sous_categorie = Categorie(
            foyer=revenus.foyer, nom="Loyers perçus", parent=revenus, nature=Nature.DEPENSE
        )

        sous_categorie.full_clean()

        assert sous_categorie.nature == Nature.REVENU

    def test_pas_de_troisieme_niveau(self):
        sous_categorie = FabriqueSousCategorie()
        petite_fille = Categorie(foyer=sous_categorie.foyer, nom="x", parent=sous_categorie)

        with pytest.raises(ValidationError):
            petite_fille.full_clean()

    def test_une_parente_avec_enfants_ne_devient_pas_sous_categorie(self):
        sous_categorie = FabriqueSousCategorie()
        parente = sous_categorie.parent
        parente.parent = FabriqueCategorie(foyer=parente.foyer)

        with pytest.raises(ValidationError):
            parente.full_clean()

    def test_parente_d_un_autre_foyer_refusee(self):
        categorie = Categorie(foyer=FabriqueFoyer(), nom="x", parent=FabriqueCategorie())

        with pytest.raises(ValidationError):
            categorie.full_clean()

    def test_noms_uniques_par_niveau(self):
        parente = FabriqueCategorie(nom="Logement")
        FabriqueSousCategorie(parent=parente, nom="Loyer")
        FabriqueSousCategorie(parent=FabriqueCategorie(foyer=parente.foyer), nom="Loyer")
        FabriqueCategorie(nom="Logement")  # autre foyer : autorisé

        with pytest.raises(IntegrityError), transaction.atomic():
            FabriqueSousCategorie(parent=parente, nom="Loyer")
        with pytest.raises(IntegrityError), transaction.atomic():
            FabriqueCategorie(foyer=parente.foyer, nom="Logement")

    def test_archiver_une_parente_archive_ses_sous_categories(self):
        sous_categorie = FabriqueSousCategorie()

        basculer_archivage_categorie(sous_categorie.parent)

        sous_categorie.refresh_from_db()
        assert sous_categorie.parent.est_archivee and sous_categorie.est_archivee

    def test_desarchiver(self):
        sous_categorie = FabriqueSousCategorie()
        basculer_archivage_categorie(sous_categorie)

        basculer_archivage_categorie(sous_categorie)

        sous_categorie.refresh_from_db()
        assert not sous_categorie.est_archivee

    def test_une_categorie_utilisee_ne_peut_pas_etre_supprimee(self):
        sous_categorie = FabriqueSousCategorie()
        compte = FabriqueCompte(foyer=sous_categorie.foyer)
        FabriqueOperation(compte=compte, categorie=sous_categorie)

        with pytest.raises(IntegrityError), transaction.atomic():
            sous_categorie.delete()


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        (D("1234.5"), "1 234,50 €"),
        (D("-0.99"), "-0,99 €"),
        (0, "0,00 €"),
        (None, ""),
    ],
)
def test_filtre_euros(valeur, attendu):
    assert euros(valeur) == attendu


class TestRegroupementParEtablissement:
    def test_regroupe_sans_tenir_compte_de_la_casse_ni_des_espaces(self):
        foyer = FabriqueFoyer()
        # La graphie en minuscules vient en premier : c'est quand même « Banque Populaire » qui
        # est retenu.
        a = FabriqueCompte(foyer=foyer, nom="Joint", etablissement=" banque  populaire ")
        b = FabriqueCompte(foyer=foyer, nom="Livret", etablissement="Banque Populaire")
        c = FabriqueCompte(foyer=foyer, nom="PEA", etablissement="Boursorama")
        d = FabriqueCompte(foyer=foyer, nom="Espèces", etablissement="")
        soldes = {
            a.pk: Decimal("100"),
            b.pk: Decimal("50"),
            c.pk: Decimal("10"),
            d.pk: Decimal("5"),
        }

        groupes = regrouper_par_etablissement([a, b, c, d], soldes)

        assert [g.nom for g in groupes] == ["Banque Populaire", "Boursorama", "Sans établissement"]
        assert [ligne.compte for ligne in groupes[0].lignes] == [a, b]
        assert [g.total for g in groupes] == [Decimal("150"), Decimal("10"), Decimal("5")]
        assert groupes[-1].est_sans_etablissement

    def test_aucun_compte(self):
        assert regrouper_par_etablissement([], {}) == []
