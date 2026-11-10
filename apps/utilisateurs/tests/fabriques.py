import factory
from factory.django import DjangoModelFactory

from apps.utilisateurs.models import Utilisateur

MOT_DE_PASSE = "un-mot-de-passe-solide-42"


class FabriqueUtilisateur(DjangoModelFactory):
    class Meta:
        model = Utilisateur

    email = factory.Sequence(lambda n: f"personne{n}@example.org")
    first_name = factory.Sequence(lambda n: f"Personne{n}")
    password = factory.django.Password(MOT_DE_PASSE)
