from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.banque.tests.fabriques import FabriqueOperation, FabriqueSousCategorie
from apps.budget.services.flux import Flux
from apps.budget.services.recap import recap_annuel

pytestmark = pytest.mark.django_db

D = Decimal
FIN_2026 = date(2026, 12, 31)


def _ligne(lignes, categorie):
    return next(ligne for ligne in lignes if ligne.categorie == categorie)


def _operation(plan, categorie, montant, jour):
    return FabriqueOperation(
        compte=plan.courant, categorie=categorie, date=jour, montant=D(montant)
    )


@pytest.fixture
def annee(mars):
    """Mars 2026 (voir `mars`) + avril 2026 + quelques opérations en 2025 et 2027."""
    _operation(mars, mars.salaire, "2100.00", date(2026, 4, 1))
    _operation(mars, mars.electricite, "-100.00", date(2026, 4, 10))
    _operation(mars, None, "50.00", date(2026, 4, 15))
    _operation(mars, mars.salaire, "1900.00", date(2025, 6, 1))
    _operation(mars, mars.electricite, "-90.00", date(2025, 6, 10))
    _operation(mars, mars.gaz, "-400.00", date(2025, 12, 31))
    _operation(mars, mars.gaz, "-777.00", date(2027, 1, 1))
    return mars


class TestFluxAnnuels:
    def test_flux_mois_par_mois(self, annee):
        recap = recap_annuel(annee.foyer, 2026, FIN_2026)

        assert recap.annee == 2026
        assert recap.mois[0] == date(2026, 1, 1) and len(recap.mois) == 12
        assert recap.flux_par_mois[2] == Flux(revenus=D("2000.00"), depenses=D("343.00"))
        assert recap.flux_par_mois[3] == Flux(revenus=D("2150.00"), depenses=D("100.00"))
        assert recap.flux_par_mois[0] == Flux()

    def test_total_de_l_annee_et_taux_d_epargne(self, annee):
        recap = recap_annuel(annee.foyer, 2026, FIN_2026)

        assert recap.total == Flux(revenus=D("4150.00"), depenses=D("443.00"))
        assert recap.total.taux_epargne == D("89.3")

    def test_comparaison_avec_l_annee_precedente(self, annee):
        recap = recap_annuel(annee.foyer, 2026, FIN_2026)

        assert recap.total_precedent == Flux(revenus=D("1900.00"), depenses=D("490.00"))

    def test_annee_sans_donnees(self, plan):
        recap = recap_annuel(plan.foyer, 2026, FIN_2026)

        assert recap.total == Flux() and recap.total_precedent == Flux()
        assert recap.total.taux_epargne is None

    def test_operations_non_classees_mois_par_mois(self, annee):
        recap = recap_annuel(annee.foyer, 2026, FIN_2026)

        assert recap.depenses_non_classees[2] == D("20.00")
        assert recap.revenus_non_classes[3] == D("50.00")
        assert recap.total_depenses_non_classees == D("20.00")
        assert recap.total_revenus_non_classes == D("50.00")


class TestCategoriesAnnuelles:
    def test_grille_par_categorie_et_par_mois(self, annee):
        recap = recap_annuel(annee.foyer, 2026, FIN_2026)

        energie = _ligne(recap.depenses, annee.energie)
        electricite = _ligne(energie.sous_lignes, annee.electricite)
        assert electricite.par_mois[2:4] == [D("138.00"), D("100.00")]
        assert electricite.total == D("238.00")
        assert energie.par_mois[2:4] == [D("213.00"), D("100.00")]
        assert energie.total == D("313.00")
        assert _ligne(recap.revenus, annee.revenus).total == D("4100.00")

    def test_ecart_avec_l_annee_precedente(self, annee):
        energie = _ligne(recap_annuel(annee.foyer, 2026, FIN_2026).depenses, annee.energie)
        gaz = _ligne(energie.sous_lignes, annee.gaz)

        assert (gaz.total, gaz.total_precedent, gaz.variation) == (
            D("75.00"),
            D("400.00"),
            D("-325.00"),
        )
        assert (energie.total_precedent, energie.variation) == (D("490.00"), D("-177.00"))

    def test_la_somme_des_lignes_retrouve_le_total(self, annee):
        recap = recap_annuel(annee.foyer, 2026, FIN_2026)

        depenses = sum(ligne.total for ligne in recap.depenses) + recap.total_depenses_non_classees
        revenus = sum(ligne.total for ligne in recap.revenus) + recap.total_revenus_non_classes
        assert (revenus, depenses) == (recap.total.revenus, recap.total.depenses)

    def test_categorie_archivee_masquee_si_vide_sur_les_deux_annees(self, annee):
        vide = FabriqueSousCategorie(parent=annee.energie, archive_le=timezone.now())
        for categorie in (annee.gaz, annee.loisirs):
            categorie.archive_le = timezone.now()
            categorie.save()

        recap_2026 = recap_annuel(annee.foyer, 2026, FIN_2026)
        sous_categories = [
            ligne.categorie for ligne in _ligne(recap_2026.depenses, annee.energie).sous_lignes
        ]
        assert annee.gaz in sous_categories and vide not in sous_categories
        assert annee.loisirs in [ligne.categorie for ligne in recap_2026.depenses]

        recap_2029 = recap_annuel(annee.foyer, 2029, date(2029, 12, 31))
        assert annee.loisirs not in [ligne.categorie for ligne in recap_2029.depenses]


class TestComptesAnnuels:
    def test_soldes_de_fin_de_mois(self, annee):
        recap = recap_annuel(annee.foyer, 2026, FIN_2026)

        courant = _compte(recap, annee.courant)
        # Début d'année : 1000 + 1900 − 90 − 400 en 2025.
        assert courant.solde_debut == D("2410.00")
        assert courant.fins_de_mois[1:4] == [D("2410.00"), D("3767.00"), D("5817.00")]
        assert (courant.solde_fin, courant.variation) == (D("5817.00"), D("3407.00"))

    def test_les_mois_a_venir_restent_vides(self, annee):
        recap = recap_annuel(annee.foyer, 2026, aujourd_hui=date(2026, 3, 20))

        courant = _compte(recap, annee.courant)
        assert courant.fins_de_mois[3:] == [None] * 9
        # Mars en cours : solde arrêté au 20, toutes les opérations de mars sont antérieures.
        assert courant.fins_de_mois[2] == D("3767.00")
        assert courant.solde_fin == D("3767.00")

    def test_annee_future_aucun_solde_mensuel(self, annee):
        recap = recap_annuel(annee.foyer, 2028, aujourd_hui=date(2026, 3, 20))

        courant = _compte(recap, annee.courant)
        assert courant.fins_de_mois == [None] * 12
        assert courant.solde_fin == courant.solde_debut
        assert courant.variation == D("0.00")

    def test_placement_valorise_par_ses_releves(self, annee):
        pea = _compte(recap_annuel(annee.foyer, 2026, FIN_2026), annee.pea)

        assert pea.solde_debut == D("0.00")
        assert pea.fins_de_mois[0:3] == [D("0.00"), D("5000.00"), D("5200.00")]

    def test_patrimoine(self, annee):
        recap = recap_annuel(annee.foyer, 2026, FIN_2026)

        assert recap.patrimoine_debut == D("2410.00")
        # 5817 (courant) + 300 (livret) + 5200 (PEA).
        assert recap.patrimoine_fin == D("11317.00")
        assert recap.variation_du_patrimoine == D("8907.00")

    def test_compte_archive_masque_s_il_n_a_pas_varie(self, annee):
        for compte in (annee.livret, annee.pea):
            compte.archive_le = timezone.now()
            compte.save()

        comptes_2026 = [ligne.compte for ligne in recap_annuel(annee.foyer, 2026, FIN_2026).comptes]
        comptes_2029 = [
            ligne.compte for ligne in recap_annuel(annee.foyer, 2029, date(2029, 12, 31)).comptes
        ]

        assert annee.livret in comptes_2026
        assert annee.livret not in comptes_2029 and annee.courant in comptes_2029

    def test_aujourd_hui_par_defaut(self, annee):
        recap = recap_annuel(annee.foyer, date.today().year)

        assert len(recap.comptes) == 3


def _compte(recap, compte):
    return next(ligne for ligne in recap.comptes if ligne.compte == compte)
