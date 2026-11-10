from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.banque.models import Categorie, Compte, Nature, Operation, ReleveSolde, TypeCompte
from apps.foyers.tests.fabriques import FabriqueFoyer


class FabriqueCompte(DjangoModelFactory):
    class Meta:
        model = Compte

    foyer = factory.SubFactory(FabriqueFoyer)
    nom = factory.Sequence(lambda n: f"Compte {n}")
    type = TypeCompte.COURANT
    solde_initial = Decimal("0.00")
    ouvert_le = date(2026, 1, 1)


class FabriqueCategorie(DjangoModelFactory):
    """Catégorie parente."""

    class Meta:
        model = Categorie

    foyer = factory.SubFactory(FabriqueFoyer)
    nom = factory.Sequence(lambda n: f"Catégorie {n}")
    nature = Nature.DEPENSE


class FabriqueSousCategorie(FabriqueCategorie):
    parent = factory.SubFactory(FabriqueCategorie)
    foyer = factory.SelfAttribute("parent.foyer")
    nature = factory.SelfAttribute("parent.nature")
    nom = factory.Sequence(lambda n: f"Sous-catégorie {n}")


class FabriqueOperation(DjangoModelFactory):
    """Le foyer est celui du compte : toujours passer `compte=` pour choisir le foyer."""

    class Meta:
        model = Operation

    compte = factory.SubFactory(FabriqueCompte)
    foyer = factory.SelfAttribute("compte.foyer")
    date = date(2026, 3, 15)
    libelle = factory.Sequence(lambda n: f"Opération {n}")
    montant = Decimal("-10.00")


class FabriqueReleveSolde(DjangoModelFactory):
    class Meta:
        model = ReleveSolde

    compte = factory.SubFactory(FabriqueCompte, type=TypeCompte.PEA)
    foyer = factory.SelfAttribute("compte.foyer")
    date = date(2026, 3, 31)
    montant = Decimal("1000.00")
