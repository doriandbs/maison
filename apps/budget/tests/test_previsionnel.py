from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.banque.tests.fabriques import FabriqueSousCategorie
from apps.budget.models import LigneBudget
from apps.budget.services.previsionnel import budgets_du_mois, enregistrer_budgets

from .fabriques import FabriqueLigneBudget

pytestmark = pytest.mark.django_db

D = Decimal
JANVIER, FEVRIER, MARS, AVRIL = (date(2026, m, 1) for m in (1, 2, 3, 4))


class TestBudgetsDuMois:
    def test_un_budget_vaut_pour_son_mois_et_les_suivants(self, plan):
        FabriqueLigneBudget(categorie=plan.electricite, mois=FEVRIER, montant=D("120.00"))

        assert budgets_du_mois(plan.foyer, JANVIER) == {}
        assert budgets_du_mois(plan.foyer, FEVRIER) == {plan.electricite.pk: D("120.00")}
        assert budgets_du_mois(plan.foyer, date(2027, 6, 1)) == {plan.electricite.pk: D("120.00")}

    def test_une_ligne_plus_recente_remplace_la_precedente(self, plan):
        FabriqueLigneBudget(categorie=plan.electricite, mois=JANVIER, montant=D("120.00"))
        FabriqueLigneBudget(categorie=plan.electricite, mois=MARS, montant=D("140.00"))

        assert budgets_du_mois(plan.foyer, FEVRIER)[plan.electricite.pk] == D("120.00")
        assert budgets_du_mois(plan.foyer, MARS)[plan.electricite.pk] == D("140.00")

    def test_une_surcharge_ponctuelle_ne_vaut_que_pour_son_mois(self, plan):
        FabriqueLigneBudget(categorie=plan.sorties, mois=JANVIER, montant=D("100.00"))
        FabriqueLigneBudget(
            categorie=plan.sorties, mois=FEVRIER, montant=D("400.00"), ponctuel=True
        )

        assert budgets_du_mois(plan.foyer, JANVIER)[plan.sorties.pk] == D("100.00")
        assert budgets_du_mois(plan.foyer, FEVRIER)[plan.sorties.pk] == D("400.00")
        assert budgets_du_mois(plan.foyer, MARS)[plan.sorties.pk] == D("100.00")

    def test_un_montant_nul_retire_le_budget(self, plan):
        FabriqueLigneBudget(categorie=plan.gaz, mois=JANVIER, montant=D("70.00"))
        FabriqueLigneBudget(categorie=plan.gaz, mois=MARS, montant=D("0.00"))
        FabriqueLigneBudget(categorie=plan.sorties, mois=JANVIER, montant=D("100.00"))
        FabriqueLigneBudget(categorie=plan.sorties, mois=FEVRIER, montant=D("0.00"), ponctuel=True)

        assert plan.gaz.pk in budgets_du_mois(plan.foyer, FEVRIER)
        assert plan.gaz.pk not in budgets_du_mois(plan.foyer, MARS)
        assert plan.sorties.pk not in budgets_du_mois(plan.foyer, FEVRIER)
        assert plan.sorties.pk in budgets_du_mois(plan.foyer, MARS)

    def test_les_budgets_des_autres_foyers_sont_ignores(self, plan):
        FabriqueLigneBudget()

        assert budgets_du_mois(plan.foyer, AVRIL) == {}


class TestEnregistrerBudgets:
    def test_cree_les_lignes_a_partir_du_mois(self, plan):
        modifies = enregistrer_budgets(
            foyer=plan.foyer,
            mois=MARS,
            montants={plan.electricite.pk: D("120.00"), plan.loisirs.pk: D("250.00")},
            ponctuel=False,
        )

        assert modifies == 2
        assert budgets_du_mois(plan.foyer, AVRIL) == {
            plan.electricite.pk: D("120.00"),
            plan.loisirs.pk: D("250.00"),
        }
        assert budgets_du_mois(plan.foyer, FEVRIER) == {}

    def test_ne_touche_pas_aux_montants_inchanges(self, plan):
        FabriqueLigneBudget(categorie=plan.electricite, mois=JANVIER, montant=D("120.00"))

        modifies = enregistrer_budgets(
            foyer=plan.foyer,
            mois=MARS,
            montants={plan.electricite.pk: D("120.00"), plan.gaz.pk: None},
            ponctuel=False,
        )

        assert modifies == 0
        assert LigneBudget.objects.count() == 1

    def test_ponctuel_ne_change_que_le_mois(self, plan):
        FabriqueLigneBudget(categorie=plan.sorties, mois=JANVIER, montant=D("100.00"))

        enregistrer_budgets(
            foyer=plan.foyer, mois=FEVRIER, montants={plan.sorties.pk: D("400.00")}, ponctuel=True
        )

        assert budgets_du_mois(plan.foyer, FEVRIER)[plan.sorties.pk] == D("400.00")
        assert budgets_du_mois(plan.foyer, MARS)[plan.sorties.pk] == D("100.00")

    def test_une_valeur_durable_remplace_la_surcharge_du_meme_mois(self, plan):
        FabriqueLigneBudget(
            categorie=plan.sorties, mois=FEVRIER, montant=D("400.00"), ponctuel=True
        )

        enregistrer_budgets(
            foyer=plan.foyer, mois=FEVRIER, montants={plan.sorties.pk: D("150.00")}, ponctuel=False
        )

        assert budgets_du_mois(plan.foyer, FEVRIER)[plan.sorties.pk] == D("150.00")
        assert not LigneBudget.objects.filter(ponctuel=True).exists()

    def test_vider_un_champ_retire_le_budget_a_partir_du_mois(self, plan):
        FabriqueLigneBudget(categorie=plan.gaz, mois=JANVIER, montant=D("70.00"))

        enregistrer_budgets(
            foyer=plan.foyer, mois=MARS, montants={plan.gaz.pk: None}, ponctuel=False
        )

        assert plan.gaz.pk in budgets_du_mois(plan.foyer, FEVRIER)
        assert plan.gaz.pk not in budgets_du_mois(plan.foyer, MARS)

    def test_ressaisir_le_meme_mois_met_a_jour_la_ligne(self, plan):
        for montant in ("120.00", "130.00"):
            enregistrer_budgets(
                foyer=plan.foyer,
                mois=MARS,
                montants={plan.electricite.pk: D(montant)},
                ponctuel=False,
            )

        assert LigneBudget.objects.get().montant == D("130.00")

    def test_ignore_les_categories_d_un_autre_foyer_et_les_revenus(self, plan):
        etrangere = FabriqueSousCategorie()

        modifies = enregistrer_budgets(
            foyer=plan.foyer,
            mois=MARS,
            montants={etrangere.pk: D("50.00"), plan.salaire.pk: D("50.00")},
            ponctuel=False,
        )

        assert modifies == 0
        assert not LigneBudget.objects.exists()


class TestContraintes:
    def test_le_mois_est_toujours_un_premier_du_mois(self, plan):
        with pytest.raises(IntegrityError), transaction.atomic():
            FabriqueLigneBudget(categorie=plan.gaz, mois=date(2026, 3, 15))

    def test_montant_negatif_refuse(self, plan):
        with pytest.raises(IntegrityError), transaction.atomic():
            FabriqueLigneBudget(categorie=plan.gaz, montant=D("-1.00"))

    def test_une_seule_ligne_par_categorie_mois_et_portee(self, plan):
        FabriqueLigneBudget(categorie=plan.gaz, mois=MARS)
        FabriqueLigneBudget(categorie=plan.gaz, mois=MARS, ponctuel=True)

        with pytest.raises(IntegrityError), transaction.atomic():
            FabriqueLigneBudget(categorie=plan.gaz, mois=MARS)
