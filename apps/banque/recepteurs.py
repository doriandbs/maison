from typing import Any

from django.dispatch import receiver

from apps.foyers.models import Foyer
from apps.foyers.signaux import foyer_cree

from .services.categories import creer_categories_par_defaut


@receiver(foyer_cree)
def initialiser_les_categories(sender: Any, foyer: Foyer, **kwargs: Any) -> None:
    creer_categories_par_defaut(foyer)
