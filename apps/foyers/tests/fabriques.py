from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.foyers.models import Adhesion, Foyer, Invitation, Role
from apps.foyers.services import empreinte
from apps.utilisateurs.tests.fabriques import FabriqueUtilisateur


class FabriqueFoyer(DjangoModelFactory):
    class Meta:
        model = Foyer

    nom = factory.Sequence(lambda n: f"Foyer {n}")


class FabriqueAdhesion(DjangoModelFactory):
    class Meta:
        model = Adhesion

    foyer = factory.SubFactory(FabriqueFoyer)
    utilisateur = factory.SubFactory(FabriqueUtilisateur)
    role = Role.MEMBRE


class FabriqueInvitation(DjangoModelFactory):
    class Meta:
        model = Invitation

    foyer = factory.SubFactory(FabriqueFoyer)
    email = factory.Sequence(lambda n: f"invite{n}@example.org")
    role = Role.MEMBRE
    empreinte_jeton = factory.Sequence(lambda n: empreinte(f"jeton-{n}"))
    expire_le = factory.LazyFunction(lambda: timezone.now() + timedelta(days=7))
