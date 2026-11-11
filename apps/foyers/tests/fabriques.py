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


def espace_de(utilisateur=None) -> Adhesion:  # type: ignore[no-untyped-def]
    """Adhésion d'une personne à son espace financier (créé sans catégories par défaut)."""
    from apps.foyers.espaces import espace_personnel

    utilisateur = utilisateur or FabriqueUtilisateur()
    espace = espace_personnel(utilisateur, categories=False)
    return Adhesion.objects.select_related("foyer").get(foyer=espace, utilisateur=utilisateur)


def acces_a(espace: Adhesion, role: str = Role.MEMBRE) -> Adhesion:
    """Quelqu'un qui partage un foyer avec le titulaire de `espace`, avec ce rôle.

    Renvoie son adhésion au foyer partagé (principal) ; il voit l'espace via ce foyer.
    """
    foyer = FabriqueFoyer()
    FabriqueAdhesion(foyer=foyer, utilisateur=espace.utilisateur, role=Role.PROPRIETAIRE)
    return FabriqueAdhesion(foyer=foyer, role=role, est_principal=True)


def voir_espace(client, espace: Adhesion):  # type: ignore[no-untyped-def]
    """Fait afficher à ce client les finances de `espace` (comme le sélecteur « Finances de »)."""
    from apps.foyers.middleware import CLE_SESSION_ESPACE

    session = client.session
    session[CLE_SESSION_ESPACE] = espace.foyer_id
    session.save()
    return client
