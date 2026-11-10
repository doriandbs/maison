from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.banque.tests.fabriques import FabriqueSousCategorie
from apps.budget.models import LigneBudget


class FabriqueLigneBudget(DjangoModelFactory):
    class Meta:
        model = LigneBudget

    categorie = factory.SubFactory(FabriqueSousCategorie)
    foyer = factory.SelfAttribute("categorie.foyer")
    mois = date(2026, 1, 1)
    montant = Decimal("100.00")
