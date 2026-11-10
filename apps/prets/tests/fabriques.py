from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.foyers.tests.fabriques import FabriqueFoyer
from apps.prets.models import Pret, RemboursementAnticipe


class FabriquePret(DjangoModelFactory):
    class Meta:
        model = Pret

    foyer = factory.SubFactory(FabriqueFoyer)
    nom = factory.Sequence(lambda n: f"Crédit {n}")
    capital = Decimal("200000.00")
    taux_annuel = Decimal("3.500")
    duree_mois = 300
    premiere_echeance = date(2026, 1, 5)


class FabriqueRemboursement(DjangoModelFactory):
    class Meta:
        model = RemboursementAnticipe

    pret = factory.SubFactory(FabriquePret)
    foyer = factory.SelfAttribute("pret.foyer")
    date = date(2031, 1, 1)
    montant = Decimal("20000.00")
