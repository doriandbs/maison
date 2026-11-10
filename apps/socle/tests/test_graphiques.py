from decimal import Decimal as D

import pytest

from apps.socle.graphiques import (
    HAUTEUR,
    LARGEUR,
    LARGEUR_BARRE_MAX,
    MARGE_BAS,
    MARGE_DROITE,
    MARGE_GAUCHE,
    Barre,
    courbe,
    euros_compacts,
    graduations,
    histogramme_groupe,
)


@pytest.mark.parametrize(
    ("minimum", "maximum", "attendu"),
    [
        (0, 37_500, [0, 10_000, 20_000, 30_000, 40_000]),
        (0, 950, [0, 250, 500, 750, 1000]),
        (-1200, 3100, [-2000, 0, 2000, 4000]),
        (0, 0, [0, 0.25, 0.5, 0.75, 1]),
        (5, 5, [0, 2, 4, 6]),
    ],
)
def test_graduations_rondes(minimum, maximum, attendu):
    assert graduations(minimum, maximum) == attendu


@pytest.mark.parametrize(
    ("valeur", "texte"),
    [
        (850, "850 €"),
        (12_000, "12 k€"),
        (12_500, "12,5 k€"),
        (1_250_000, "1,2 M€"),
        (2_000_000, "2 M€"),
        (-3_000, "−3 k€"),
    ],
)
def test_euros_compacts(valeur, texte):
    assert euros_compacts(valeur) == texte


class TestCourbe:
    def test_un_seul_point_ne_fait_pas_de_courbe(self):
        assert courbe([("Mars", "mars", D("10"))]) is None

    def test_geometrie(self):
        valeurs = [(f"Mois {i}", f"m{i}", D(1000 * i)) for i in range(1, 25)]

        resultat = courbe(valeurs)

        assert resultat.points[0].x == MARGE_GAUCHE
        assert resultat.points[-1].x == LARGEUR - MARGE_DROITE
        assert resultat.points[-1].y < resultat.points[0].y  # plus haut = plus grand
        assert resultat.chemin.startswith(f"M{float(MARGE_GAUCHE)},")
        assert resultat.aire.endswith("Z")
        assert len(resultat.etiquettes_x) <= 8
        assert resultat.etiquettes_x[-1].texte == "m24"  # le dernier mois est toujours nommé
        assert resultat.y_zero is None
        assert resultat.dernier.infobulle.startswith("24 000,00")

    def test_valeurs_negatives_ligne_du_zero(self):
        resultat = courbe([("a", "a", D("-500")), ("b", "b", D("1500"))])

        assert resultat.y_zero is not None
        assert resultat.graduations[0].texte.startswith("−")


class TestHistogramme:
    def _histogramme(self, annee, avant):
        categories = [(f"Mois {i}", f"m{i}") for i in range(1, len(annee) + 1)]
        return histogramme_groupe(categories, annee, avant, ("2026", "2025"))

    def test_rien_a_dessiner(self):
        assert self._histogramme([None, D("0")], [D("0"), D("0")]) is None

    def test_barres_fines_et_mois_futurs_vides(self):
        resultat = self._histogramme([D("100"), None], [D("80"), D("120")])

        premier, second = resultat.groupes
        assert [b.serie for b in premier.barres] == [2, 1]  # année précédente à gauche
        assert [b.serie for b in second.barres] == [2]
        assert all(b.largeur <= LARGEUR_BARRE_MAX for g in resultat.groupes for b in g.barres)
        assert all(
            round(b.y + b.hauteur, 2) == HAUTEUR - MARGE_BAS
            for g in resultat.groupes
            for b in g.barres
        )
        assert "2026 : –" in second.infobulle and "2025 : 120,00" in second.infobulle

    def test_barre_arrondie_cote_valeur_seulement(self):
        barre = Barre(x=10, y=50, largeur=20, hauteur=100, serie=1)

        assert barre.chemin.startswith("M10,150 V54")  # coin carré sur la ligne de base
        assert "Q10,50 14,50" in barre.chemin and barre.chemin.endswith("V150 Z")

    def test_petite_barre_rayon_reduit(self):
        assert "V51" in Barre(x=0, y=50, largeur=20, hauteur=1, serie=1).chemin
