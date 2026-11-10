from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q, Sum

from apps.banque.models import Categorie, Compte, Nature, Operation
from apps.banque.services.soldes import soldes_des_comptes
from apps.foyers.models import Foyer

from .flux import (
    ZERO,
    Flux,
    MouvementsParCategorie,
    calculer_flux,
    dernier_du_mois,
    montant_realise,
    mouvements_par_mois,
    premier_du_mois,
)
from .previsionnel import budgets_du_mois


@dataclass
class LigneCategorie:
    categorie: Categorie
    realise: Decimal
    budget: Decimal | None = None
    sous_lignes: list[LigneCategorie] = field(default_factory=list)

    @property
    def reste(self) -> Decimal | None:
        return None if self.budget is None else self.budget - self.realise

    @property
    def montant_depasse(self) -> Decimal:
        return self.realise - self.budget if self.depassement else ZERO  # type: ignore[operator]

    @property
    def depassement(self) -> bool:
        return (
            self.budget is not None
            and self.categorie.nature == Nature.DEPENSE
            and self.realise > self.budget
        )

    @property
    def est_vide(self) -> bool:
        return self.realise == 0 and self.budget is None


@dataclass
class LigneCompte:
    compte: Compte
    solde_debut: Decimal
    revenus: Decimal
    depenses: Decimal
    virements: Decimal
    solde_fin: Decimal

    @property
    def variation_de_valeur(self) -> Decimal:
        """Ce que les opérations n'expliquent pas : plus ou moins-value d'un placement."""
        attendu = self.solde_debut + self.revenus - self.depenses + self.virements
        return self.solde_fin - attendu

    @property
    def a_bouge(self) -> bool:
        return any((self.revenus, self.depenses, self.virements, self.variation_de_valeur))


@dataclass
class TableauMensuel:
    mois: date
    flux: Flux
    depenses: list[LigneCategorie]
    revenus: list[LigneCategorie]
    revenus_non_classes: Decimal
    depenses_non_classees: Decimal
    comptes: list[LigneCompte]

    @property
    def alertes(self) -> list[LigneCategorie]:
        """Catégories en dépassement, parentes et sous-catégories confondues."""
        toutes = [ligne for parente in self.depenses for ligne in (parente, *parente.sous_lignes)]
        return [ligne for ligne in toutes if ligne.depassement]

    @property
    def budget_total(self) -> Decimal:
        return sum((ligne.budget or ZERO for ligne in self.depenses), ZERO)


def lignes_par_categorie(
    categories: list[Categorie], mouvements: MouvementsParCategorie, budgets: dict[int, Decimal]
) -> list[LigneCategorie]:
    """Arbre parente → sous-catégories.

    Le réalisé d'une parente est la somme de ses sous-catégories. Son budget est celui
    saisi sur elle s'il existe, sinon la somme des budgets de ses sous-catégories.
    Les catégories archivées n'apparaissent que si elles portent un montant.
    """
    enfants: dict[int, list[Categorie]] = {}
    for categorie in categories:
        if categorie.parent_id is not None:
            enfants.setdefault(categorie.parent_id, []).append(categorie)

    lignes = []
    for parente in (c for c in categories if c.parent_id is None):
        sous_lignes = [
            LigneCategorie(
                categorie=enfant,
                realise=montant_realise(enfant.nature, mouvements.get(enfant.pk, (ZERO, ZERO))),
                budget=budgets.get(enfant.pk),
            )
            for enfant in enfants.get(parente.pk, [])
        ]
        sous_lignes = [s for s in sous_lignes if not (s.categorie.est_archivee and s.est_vide)]
        budgets_enfants = [s.budget for s in sous_lignes if s.budget is not None]
        ligne = LigneCategorie(
            categorie=parente,
            realise=sum((s.realise for s in sous_lignes), ZERO),
            budget=budgets.get(parente.pk, sum(budgets_enfants, ZERO) if budgets_enfants else None),
            sous_lignes=sous_lignes,
        )
        if not (parente.est_archivee and ligne.est_vide):
            lignes.append(ligne)
    return lignes


def lignes_par_compte(foyer: Foyer, debut: date, fin: date) -> list[LigneCompte]:
    hors_virement = Q(groupe_virement__isnull=True)
    sans_categorie = Q(categorie__isnull=True)
    totaux: dict[int, dict[str, Any]] = {
        ligne["compte_id"]: dict(ligne)
        for ligne in Operation.objects.du_foyer(foyer)
        .filter(date__range=(debut, fin))
        .order_by()
        .values("compte_id")
        .annotate(
            revenus=Sum(
                "montant",
                filter=hors_virement
                & (Q(categorie__nature=Nature.REVENU) | (sans_categorie & Q(montant__gt=0))),
            ),
            depenses=Sum(
                "montant",
                filter=hors_virement
                & (Q(categorie__nature=Nature.DEPENSE) | (sans_categorie & Q(montant__lt=0))),
            ),
            virements=Sum("montant", filter=Q(groupe_virement__isnull=False)),
        )
    }
    soldes_debut = soldes_des_comptes(foyer, debut - timedelta(days=1))
    soldes_fin = soldes_des_comptes(foyer, fin)
    lignes = []
    for compte in Compte.objects.du_foyer(foyer):
        du_compte = totaux.get(compte.pk, {})
        ligne = LigneCompte(
            compte=compte,
            solde_debut=soldes_debut[compte.pk],
            revenus=du_compte.get("revenus") or ZERO,
            depenses=-(du_compte.get("depenses") or ZERO),
            virements=du_compte.get("virements") or ZERO,
            solde_fin=soldes_fin[compte.pk],
        )
        if not compte.est_archive or ligne.a_bouge:
            lignes.append(ligne)
    return lignes


def tableau_mensuel(foyer: Foyer, annee: int, mois: int) -> TableauMensuel:
    debut, fin = premier_du_mois(annee, mois), dernier_du_mois(annee, mois)
    mouvements = mouvements_par_mois(foyer, debut, fin).get((annee, mois), {})
    categories = list(Categorie.objects.du_foyer(foyer))
    lignes = lignes_par_categorie(categories, mouvements, budgets_du_mois(foyer, debut))
    entrees_non_classees, sorties_non_classees = mouvements.get(None, (ZERO, ZERO))
    return TableauMensuel(
        mois=debut,
        flux=calculer_flux(mouvements, {c.pk: c.nature for c in categories}),
        depenses=[ligne for ligne in lignes if ligne.categorie.nature == Nature.DEPENSE],
        revenus=[ligne for ligne in lignes if ligne.categorie.nature == Nature.REVENU],
        revenus_non_classes=entrees_non_classees,
        depenses_non_classees=-sorties_non_classees,
        comptes=lignes_par_compte(foyer, debut, fin),
    )
