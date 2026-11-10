from decimal import Decimal as D

import pytest

from apps.socle.navigation import section_de
from apps.socle.templatetags.formats import part_de, valeur_brute
from apps.socle.templatetags.icones import TRACES, icone


@pytest.mark.parametrize(
    ("espace", "nom", "section"),
    [
        ("", "accueil", "accueil"),
        ("banque", "comptes", "comptes"),
        ("banque", "ajouter_releve", "comptes"),
        ("banque", "modifier_operation", "operations"),
        ("banque", "ajouter_virement", "operations"),
        ("banque", "archiver_categorie", "categories"),
        ("budget", "mois", "budget"),
        ("documents", "fichier", "documents"),
        ("foyers", "membres", "membres"),
        ("foyers", "liste", "foyers"),
    ],
)
def test_section_active_du_menu(espace, nom, section):
    assert section_de(espace, nom) == section


@pytest.mark.parametrize(
    ("valeur", "total", "attendu"),
    [
        (D("50"), D("200"), "25.0%"),
        (D("300"), D("200"), "100.0%"),
        (D("-10"), D("200"), "0.0%"),
        (D("10"), D("0"), "0%"),
        (None, D("100"), "0%"),
    ],
)
def test_part_de_est_bornee(valeur, total, attendu):
    assert part_de(valeur, total) == attendu


def test_valeur_brute_garde_le_signe():
    assert valeur_brute(D("-12.5")) == "-12.50"
    assert valeur_brute(None) == "0.00"


def test_icone_decorative():
    svg = icone("accueil")
    assert 'aria-hidden="true"' in svg and TRACES["accueil"] in svg


def test_icone_inconnue():
    with pytest.raises(KeyError):
        icone("inexistante")
