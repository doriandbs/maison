"""Espaces financiers personnels et accès croisés entre membres d'un même foyer.

Chaque personne a son espace (comptes, opérations, budget, crédits…), utilisable sans foyer.
Dans un foyer partagé, chaque membre accède aussi à l'espace des autres membres, avec le rôle
qu'il a dans ce foyer : lecture seule → consultation, membre et plus → modification.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import QuerySet

from apps.utilisateurs.models import Utilisateur

from .models import Adhesion, Foyer, Role
from .signaux import foyer_cree


@transaction.atomic
def espace_personnel(utilisateur: Utilisateur, categories: bool = True) -> Foyer:
    """L'espace de la personne, créé à la première demande (avec les catégories par défaut)."""
    existant = Foyer.objects.filter(personne=utilisateur).first()
    if existant is not None:
        return existant
    prenom = utilisateur.first_name or utilisateur.email.split("@")[0]
    espace = Foyer.objects.create(
        nom=f"Finances de {prenom}"[:100], personne=utilisateur, cree_par=utilisateur
    )
    Adhesion.objects.create(foyer=espace, utilisateur=utilisateur, role=Role.PROPRIETAIRE)
    if categories:
        foyer_cree.send(sender=Foyer, foyer=espace)
    return espace


def acces_aux_espaces(utilisateur: Utilisateur, foyer_partage: Foyer | None) -> list[Adhesion]:
    """Son propre espace (propriétaire), puis ceux des autres membres du foyer partagé.

    Pour l'espace d'un autre, l'adhésion renvoyée n'est pas enregistrée : elle porte le rôle
    qu'a l'utilisateur dans le foyer partagé, et sert aux mêmes contrôles que d'habitude.
    """
    propre = Adhesion.objects.select_related("foyer__personne").get(
        utilisateur=utilisateur, foyer=espace_personnel(utilisateur)
    )
    acces = [propre]
    if foyer_partage is None or foyer_partage.est_personnel:
        return acces
    mon_role = (
        Adhesion.objects.filter(foyer=foyer_partage, utilisateur=utilisateur)
        .values_list("role", flat=True)
        .first()
    )
    if mon_role is None:
        return acces
    autres = (
        Adhesion.objects.filter(foyer=foyer_partage)
        .exclude(utilisateur=utilisateur)
        .select_related("utilisateur")
        .order_by("utilisateur__first_name", "utilisateur__email")
    )
    espaces = {
        espace.personne_id: espace
        for espace in Foyer.objects.filter(
            personne__in=[a.utilisateur_id for a in autres]
        ).select_related("personne")
    }
    for membre in autres:
        espace = espaces.get(membre.utilisateur_id) or espace_personnel(membre.utilisateur)
        acces.append(Adhesion(foyer=espace, utilisateur=utilisateur, role=mon_role))
    return acces


def proches(utilisateur: Utilisateur) -> QuerySet[Utilisateur]:
    """Les personnes avec qui l'on partage au moins un foyer (pour un crédit à plusieurs)."""
    foyers = Foyer.objects.filter(personne__isnull=True, adhesions__utilisateur=utilisateur)
    return (
        Utilisateur.objects.filter(adhesions__foyer__in=foyers)
        .exclude(pk=utilisateur.pk)
        .distinct()
        .order_by("first_name", "email")
    )
