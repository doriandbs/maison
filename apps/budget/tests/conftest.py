from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.banque.models import Nature, TypeCompte
from apps.banque.services.operations import creer_virement
from apps.banque.tests.fabriques import (
    FabriqueCategorie,
    FabriqueCompte,
    FabriqueOperation,
    FabriqueReleveSolde,
    FabriqueSousCategorie,
)
from apps.foyers.tests.fabriques import FabriqueFoyer

D = Decimal


@pytest.fixture
def foyer():
    return FabriqueFoyer()


@pytest.fixture
def plan(foyer):
    """Catégories et comptes d'un foyer type, sans aucune opération."""
    energie = FabriqueCategorie(foyer=foyer, nom="Énergie")
    loisirs = FabriqueCategorie(foyer=foyer, nom="Loisirs")
    revenus = FabriqueCategorie(foyer=foyer, nom="Revenus", nature=Nature.REVENU)
    return SimpleNamespace(
        foyer=foyer,
        energie=energie,
        electricite=FabriqueSousCategorie(parent=energie, nom="Électricité"),
        gaz=FabriqueSousCategorie(parent=energie, nom="Gaz"),
        loisirs=loisirs,
        sorties=FabriqueSousCategorie(parent=loisirs, nom="Sorties"),
        revenus=revenus,
        salaire=FabriqueSousCategorie(parent=revenus, nom="Salaire"),
        courant=FabriqueCompte(foyer=foyer, nom="Courant", solde_initial=D("1000.00")),
        livret=FabriqueCompte(foyer=foyer, nom="Livret", type=TypeCompte.LIVRET),
        pea=FabriqueCompte(foyer=foyer, nom="PEA", type=TypeCompte.PEA),
    )


@pytest.fixture
def mars(plan):
    """Mars 2026 : salaire 2000, électricité 138 (dont 12 remboursés), gaz 75, sorties 110,
    une dépense non classée de 20, un virement de 300 vers le livret."""

    def operation(categorie, montant, jour=10, compte=None):
        return FabriqueOperation(
            compte=compte or plan.courant,
            categorie=categorie,
            date=date(2026, 3, jour),
            montant=D(montant),
        )

    operation(plan.salaire, "2000.00", jour=1)
    operation(plan.electricite, "-150.00")
    operation(plan.electricite, "12.00", jour=20)
    operation(plan.gaz, "-75.00")
    operation(plan.sorties, "-110.00")
    operation(None, "-20.00")
    creer_virement(
        source=plan.courant,
        destination=plan.livret,
        date_virement=date(2026, 3, 5),
        montant=D("300.00"),
        libelle="Épargne",
    )
    FabriqueReleveSolde(compte=plan.pea, date=date(2026, 2, 28), montant=D("5000.00"))
    FabriqueReleveSolde(compte=plan.pea, date=date(2026, 3, 31), montant=D("5200.00"))
    # Bruit : un autre foyer, qui ne doit jamais entrer dans les calculs.
    FabriqueOperation(
        compte=FabriqueCompte(),
        categorie=FabriqueSousCategorie(),
        date=date(2026, 3, 10),
        montant=D("-9999.00"),
    )
    return plan
