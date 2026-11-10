from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.banque.tests.fabriques import FabriqueOperation, FabriqueSousCategorie
from apps.budget.services.flux import Flux
from apps.budget.services.tableau import tableau_mensuel

from .fabriques import FabriqueLigneBudget

pytestmark = pytest.mark.django_db

D = Decimal
JANVIER = date(2026, 1, 1)


def _ligne(lignes, categorie):
    return next(ligne for ligne in lignes if ligne.categorie == categorie)


class TestFlux:
    def test_epargne_et_taux(self):
        flux = Flux(revenus=D("2000.00"), depenses=D("1500.00"))

        assert (flux.epargne, flux.taux_epargne) == (D("500.00"), D("25.0"))

    def test_taux_negatif_quand_on_depense_plus_qu_on_ne_gagne(self):
        assert Flux(revenus=D("1000.00"), depenses=D("1250.00")).taux_epargne == D("-25.0")

    @pytest.mark.parametrize("revenus", [D("0.00"), D("-10.00")])
    def test_taux_indefini_sans_revenu(self, revenus):
        assert Flux(revenus=revenus, depenses=D("100.00")).taux_epargne is None


class TestFluxDuMois:
    def test_revenus_depenses_et_taux_d_epargne(self, mars):
        tableau = tableau_mensuel(mars.foyer, 2026, 3)

        # 138 + 75 + 110 + 20 non classés ; le virement de 300 ne compte pas.
        assert tableau.flux == Flux(revenus=D("2000.00"), depenses=D("343.00"))
        assert tableau.flux.taux_epargne == D("82.9")
        assert tableau.mois == date(2026, 3, 1)

    def test_les_autres_mois_ne_comptent_pas(self, mars):
        FabriqueOperation(
            compte=mars.courant, categorie=mars.gaz, date=date(2026, 2, 28), montant=D("-50.00")
        )
        FabriqueOperation(
            compte=mars.courant, categorie=mars.gaz, date=date(2026, 4, 1), montant=D("-50.00")
        )

        assert tableau_mensuel(mars.foyer, 2026, 3).flux.depenses == D("343.00")

    def test_mois_sans_operation(self, plan):
        tableau = tableau_mensuel(plan.foyer, 2026, 3)

        assert tableau.flux == Flux()
        assert tableau.alertes == []
        assert tableau.budget_total == D("0.00")

    def test_operations_non_classees(self, mars):
        FabriqueOperation(
            compte=mars.courant, categorie=None, date=date(2026, 3, 12), montant=D("35.00")
        )

        tableau = tableau_mensuel(mars.foyer, 2026, 3)

        assert tableau.depenses_non_classees == D("20.00")
        assert tableau.revenus_non_classes == D("35.00")
        assert tableau.flux.revenus == D("2035.00")


class TestLignesParCategorie:
    def test_realise_net_des_remboursements_et_parente_somme_des_enfants(self, mars):
        tableau = tableau_mensuel(mars.foyer, 2026, 3)

        energie = _ligne(tableau.depenses, mars.energie)
        assert energie.realise == D("213.00")
        assert _ligne(energie.sous_lignes, mars.electricite).realise == D("138.00")
        assert _ligne(energie.sous_lignes, mars.gaz).realise == D("75.00")
        revenus = _ligne(tableau.revenus, mars.revenus)
        assert revenus.realise == D("2000.00")
        assert [ligne.categorie for ligne in tableau.revenus] == [mars.revenus]

    def test_budget_de_la_parente_somme_des_sous_categories(self, mars):
        FabriqueLigneBudget(categorie=mars.electricite, mois=JANVIER, montant=D("120.00"))
        FabriqueLigneBudget(categorie=mars.gaz, mois=JANVIER, montant=D("70.00"))

        tableau = tableau_mensuel(mars.foyer, 2026, 3)

        energie = _ligne(tableau.depenses, mars.energie)
        assert (energie.budget, energie.reste, energie.depassement) == (
            D("190.00"),
            D("-23.00"),
            True,
        )
        assert {ligne.categorie for ligne in tableau.alertes} == {
            mars.energie,
            mars.electricite,
            mars.gaz,
        }
        assert tableau.budget_total == D("190.00")

    def test_budget_saisi_sur_la_parente_fait_foi(self, mars):
        FabriqueLigneBudget(categorie=mars.loisirs, mois=JANVIER, montant=D("250.00"))
        FabriqueLigneBudget(categorie=mars.electricite, mois=JANVIER, montant=D("120.00"))
        FabriqueLigneBudget(categorie=mars.energie, mois=JANVIER, montant=D("300.00"))

        tableau = tableau_mensuel(mars.foyer, 2026, 3)

        loisirs = _ligne(tableau.depenses, mars.loisirs)
        assert (loisirs.budget, loisirs.reste, loisirs.depassement) == (
            D("250.00"),
            D("140.00"),
            False,
        )
        assert _ligne(loisirs.sous_lignes, mars.sorties).budget is None
        energie = _ligne(tableau.depenses, mars.energie)
        assert (energie.budget, energie.depassement) == (D("300.00"), False)
        assert tableau.alertes == [_ligne(energie.sous_lignes, mars.electricite)]

    def test_sans_budget_ni_reste_ni_alerte(self, mars):
        ligne = _ligne(tableau_mensuel(mars.foyer, 2026, 3).depenses, mars.loisirs)

        assert (ligne.budget, ligne.reste, ligne.depassement) == (None, None, False)

    def test_un_revenu_superieur_au_budget_n_est_pas_une_alerte(self, mars):
        FabriqueLigneBudget(categorie=mars.salaire, mois=JANVIER, montant=D("1500.00"))

        tableau = tableau_mensuel(mars.foyer, 2026, 3)

        assert not _ligne(tableau.revenus, mars.revenus).sous_lignes[0].depassement

    def test_categorie_archivee_masquee_si_vide_visible_si_utilisee(self, mars):
        vide = FabriqueSousCategorie(parent=mars.energie, archive_le=timezone.now())
        mars.gaz.archive_le = timezone.now()
        mars.gaz.save()
        mars.loisirs.archive_le = timezone.now()
        mars.loisirs.save()

        tableau = tableau_mensuel(mars.foyer, 2026, 3)
        sous_categories = [
            ligne.categorie for ligne in _ligne(tableau.depenses, mars.energie).sous_lignes
        ]
        assert mars.gaz in sous_categories and vide not in sous_categories
        assert mars.loisirs in [ligne.categorie for ligne in tableau.depenses]

        avril = tableau_mensuel(mars.foyer, 2026, 4)
        assert mars.loisirs not in [ligne.categorie for ligne in avril.depenses]


class TestLignesParCompte:
    def test_compte_courant(self, mars):
        ligne = _compte(tableau_mensuel(mars.foyer, 2026, 3), mars.courant)

        assert (ligne.solde_debut, ligne.revenus, ligne.depenses, ligne.virements) == (
            D("1000.00"),
            D("2000.00"),
            D("343.00"),
            D("-300.00"),
        )
        assert (ligne.solde_fin, ligne.variation_de_valeur) == (D("2357.00"), D("0.00"))

    def test_compte_destinataire_d_un_virement(self, mars):
        ligne = _compte(tableau_mensuel(mars.foyer, 2026, 3), mars.livret)

        assert (ligne.virements, ligne.solde_fin) == (D("300.00"), D("300.00"))
        assert (ligne.revenus, ligne.depenses) == (D("0.00"), D("0.00"))

    def test_la_plus_value_d_un_placement_apparait_en_variation_de_valeur(self, mars):
        ligne = _compte(tableau_mensuel(mars.foyer, 2026, 3), mars.pea)

        assert (ligne.solde_debut, ligne.solde_fin) == (D("5000.00"), D("5200.00"))
        assert ligne.variation_de_valeur == D("200.00")

    def test_le_solde_de_debut_reprend_la_fin_du_mois_precedent(self, mars):
        ligne = _compte(tableau_mensuel(mars.foyer, 2026, 4), mars.courant)

        assert (ligne.solde_debut, ligne.solde_fin) == (D("2357.00"), D("2357.00"))
        assert not ligne.a_bouge

    def test_compte_archive_masque_sauf_s_il_a_bouge(self, mars):
        mars.livret.archive_le = timezone.now()
        mars.livret.save()

        assert mars.livret in _comptes(tableau_mensuel(mars.foyer, 2026, 3))
        assert mars.livret not in _comptes(tableau_mensuel(mars.foyer, 2026, 4))


def _comptes(tableau):
    return [ligne.compte for ligne in tableau.comptes]


def _compte(tableau, compte):
    return next(ligne for ligne in tableau.comptes if ligne.compte == compte)
