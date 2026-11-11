"""Périmètre des écrans de finances : ce qu'un utilisateur voit d'un coup.

Dans un foyer partagé, les écrans réunissent les finances de tous ses membres : leurs
**espaces** (comptes, opérations, relevés, crédits), et le **classement** du foyer
(catégories, règles, budget), commun à tous. Sans foyer : son seul espace, qui porte aussi
son classement. Voir docs/adr/0006.

`RequeteDeFoyer.du_foyer()` accepte un périmètre à la place d'un foyer : le code des vues et
des services reste le même, qu'il porte sur une personne ou sur tout un foyer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.foyers.models import Foyer


@dataclass(frozen=True)
class Perimetre:
    espaces: tuple[Foyer, ...]  # le sien d'abord, puis ceux des autres membres
    classement: Foyer

    @classmethod
    def de(cls, foyer: Foyer) -> Perimetre:
        """Un seul foyer, qui porte à la fois les données et le classement."""
        return cls((foyer,), foyer)

    @property
    def pk(self) -> int:
        """Identifiant stable du périmètre (celui du foyer de classement)."""
        return self.classement.pk

    @property
    def espace_propre(self) -> Foyer:
        return self.espaces[0]

    @property
    def est_partage(self) -> bool:
        return len(self.espaces) > 1 or self.classement.pk != self.espace_propre.pk

    def foyers_pour(self, modele: type[Any]) -> list[Foyer]:
        if getattr(modele, "porte_le_classement", False):
            return [self.classement]
        return list(self.espaces)

    def foyer_de_creation(self, modele: type[Any]) -> Foyer:
        """Où ranger un nouvel objet : le classement du foyer, ou son propre espace."""
        if getattr(modele, "porte_le_classement", False):
            return self.classement
        return self.espace_propre

    def contient(self, foyer_id: int, modele: type[Any]) -> bool:
        return any(foyer.pk == foyer_id for foyer in self.foyers_pour(modele))
