from datetime import date
from decimal import Decimal as D

import pytest

from apps.prets.services.amortissement import (
    Anticipe,
    Conditions,
    Differe,
    Effet,
    ajouter_mois,
    calculer,
    mensualite_constante,
    simuler,
)

IMMO = Conditions(D("200000"), D("3.5"), 300, date(2026, 1, 5))


class TestMensualite:
    def test_valeur_de_reference(self):
        # 200 000 € à 3,5 % sur 25 ans : 1 001,25 € (simulateurs bancaires).
        assert mensualite_constante(D("200000"), D("3.5"), 300) == D("1001.25")

    def test_taux_zero(self):
        assert mensualite_constante(D("1200"), D("0"), 12) == D("100.00")

    def test_aucune_echeance_restante(self):
        assert mensualite_constante(D("99.999"), D("3"), 0) == D("100.00")


class TestTableau:
    def test_pret_classique(self):
        tableau = calculer(IMMO)

        assert len(tableau.echeances) == 300
        assert tableau.mensualite_amortissement == D("1001.25")
        assert tableau.echeances[0].interets == D("583.33")  # 200 000 × 3,5 % / 12
        assert tableau.echeances[-1].capital_fin == 0
        assert tableau.total_interets == D("100373.59")
        assert tableau.date_fin == date(2050, 12, 5)
        assert tableau.cout_total == tableau.total_interets

    def test_le_capital_rembourse_egale_le_capital_emprunte(self):
        tableau = calculer(IMMO)

        assert sum(e.amortissement for e in tableau.echeances) == D("200000")

    def test_assurance_comptee_a_chaque_echeance(self):
        tableau = calculer(
            Conditions(D("10000"), D("2"), 12, date(2026, 1, 1), assurance_mensuelle=D("5"))
        )

        assert tableau.echeances[0].total == tableau.echeances[0].mensualite + D("5")
        assert tableau.total_assurance == D("60")
        assert tableau.cout_total == tableau.total_interets + D("60")

    def test_taux_zero_sans_interets(self):
        tableau = calculer(Conditions(D("1200"), D("0"), 12, date(2026, 1, 1)))

        assert tableau.total_interets == 0
        assert {e.mensualite for e in tableau.echeances} == {D("100.00")}

    def test_dates_en_fin_de_mois(self):
        assert ajouter_mois(date(2026, 1, 31), 1) == date(2026, 2, 28)
        assert ajouter_mois(date(2028, 1, 31), 1) == date(2028, 2, 29)
        assert ajouter_mois(date(2026, 11, 15), 3) == date(2027, 2, 15)
        assert ajouter_mois(date(2026, 3, 15), -3) == date(2025, 12, 15)

    def test_capital_restant_du(self):
        tableau = calculer(IMMO)

        assert tableau.capital_restant_du(date(2025, 12, 31)) == D("200000")
        assert tableau.capital_restant_du(date(2026, 1, 5)) == tableau.echeances[0].capital_fin
        assert tableau.capital_restant_du(date(2060, 1, 1)) == 0
        assert tableau.echeances_restantes(date(2026, 1, 5)) == 299
        assert tableau.mensualite_en_cours(date(2026, 1, 5)) == D("1001.25")
        assert tableau.mensualite_en_cours(date(2060, 1, 1)) is None

    def test_tableau_vide(self):
        tableau = calculer(
            Conditions(D("1000"), D("1"), 12, date(2026, 1, 1)),
            [Anticipe(date(2025, 12, 1), D("1000"))],
        )

        assert tableau.echeances == [] and tableau.date_fin is None
        assert tableau.mensualite_amortissement is None


class TestDiffere:
    def test_differe_partiel_on_paie_les_interets(self):
        tableau = calculer(
            Conditions(D("100000"), D("3"), 120, date(2026, 1, 1), D("20"), 12, Differe.PARTIEL)
        )
        differe = tableau.echeances[:12]

        assert all(e.en_differe and e.amortissement == 0 for e in differe)
        assert differe[0].total == D("250.00") + D("20")  # 100 000 × 3 % / 12 + assurance
        assert tableau.echeances[12].capital_debut == D("100000")
        assert len(tableau.echeances) == 120 and tableau.echeances[-1].capital_fin == 0

    def test_differe_total_les_interets_s_ajoutent_au_capital(self):
        tableau = calculer(
            Conditions(D("100000"), D("3"), 120, date(2026, 1, 1), D("20"), 12, Differe.TOTAL)
        )
        premiere = tableau.echeances[0]

        assert premiere.total == D("20")  # l'assurance seule
        assert premiere.capital_fin == D("100250.00")
        assert tableau.echeances[12].capital_debut > D("103000")
        assert tableau.capital_restant_du(date(2026, 12, 31)) > D("100000")
        assert tableau.echeances[-1].capital_fin == 0
        assert tableau.mensualite_amortissement == tableau.echeances[12].mensualite


class TestRemboursementAnticipe:
    def test_reduire_la_duree(self):
        simulation = simuler(IMMO, [], Anticipe(date(2031, 1, 1), D("20000"), Effet.DUREE))

        assert simulation.mois_gagnes == 38
        assert simulation.economie_interets == D("18100.83")
        assert simulation.mensualite_apres == simulation.mensualite_avant == D("1001.25")
        assert simulation.apres.capital_restant_du(date(2031, 1, 1)) == (
            simulation.avant.capital_restant_du(date(2031, 1, 1)) - D("20000")
        )

    def test_reduire_la_mensualite(self):
        simulation = simuler(IMMO, [], Anticipe(date(2031, 1, 1), D("20000"), Effet.MENSUALITE))

        assert simulation.mois_gagnes == 0
        assert simulation.mensualite_apres == D("885.25")
        assert simulation.economie_interets == D("7836.93")

    def test_impute_avant_l_echeance_suivante(self):
        tableau = calculer(IMMO, [Anticipe(date(2026, 1, 20), D("1000"))])

        assert tableau.echeances[0].anticipe == 0
        assert tableau.echeances[1].anticipe == D("1000")
        assert tableau.capital_restant_du(date(2026, 1, 20)) == tableau.echeances[1].capital_debut

    def test_rembourser_tout_solde_le_pret(self):
        tableau = calculer(IMMO, [Anticipe(date(2027, 1, 1), D("999999"))])

        assert tableau.date_fin == date(2026, 12, 5)
        assert tableau.capital_restant_du(date(2027, 1, 1)) == 0
        assert tableau.anticipes[0].montant < D("999999")  # plafonné au capital dû

    def test_deux_remboursements_avant_la_meme_echeance_le_premier_solde_tout(self):
        tableau = calculer(
            IMMO, [Anticipe(date(2026, 1, 1), D("999999")), Anticipe(date(2026, 1, 2), D("10"))]
        )

        assert tableau.echeances == [] and len(tableau.anticipes) == 1

    def test_un_remboursement_apres_le_solde_est_ignore(self):
        tableau = calculer(
            IMMO, [Anticipe(date(2027, 1, 1), D("999999")), Anticipe(date(2027, 2, 1), D("10"))]
        )

        assert len(tableau.anticipes) == 1

    def test_plusieurs_remboursements_dans_l_ordre(self):
        tableau = calculer(
            IMMO,
            [Anticipe(date(2032, 1, 1), D("5000")), Anticipe(date(2030, 1, 1), D("5000"))],
        )

        assert [a.date.year for a in tableau.anticipes] == [2030, 2032]
        assert len(tableau.echeances) < 300

    def test_pendant_un_differe_mensualite_recalculee_a_la_fin_du_differe(self):
        conditions = Conditions(
            D("100000"), D("3"), 120, date(2026, 1, 1), D("0"), 12, Differe.PARTIEL
        )

        tableau = calculer(conditions, [Anticipe(date(2026, 6, 15), D("10000"), Effet.MENSUALITE)])

        assert tableau.echeances[12].capital_debut == D("90000")
        assert tableau.mensualite_amortissement == mensualite_constante(D("90000"), D("3"), 108)


@pytest.mark.parametrize("duree", [1, 2, 12, 240, 360])
def test_toujours_solde_a_la_derniere_echeance(duree):
    tableau = calculer(Conditions(D("123456.78"), D("4.15"), duree, date(2026, 1, 31)))

    assert len(tableau.echeances) == duree
    assert tableau.echeances[-1].capital_fin == 0
    assert all(e.amortissement > 0 for e in tableau.echeances)
