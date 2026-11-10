from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from apps.banque.models import Categorie, Compte, Nature
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
)

MOIS = range(1, 13)


@dataclass
class LigneRecap:
    categorie: Categorie
    par_mois: list[Decimal]
    total_precedent: Decimal
    sous_lignes: list[LigneRecap] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum(self.par_mois, ZERO)

    @property
    def variation(self) -> Decimal:
        return self.total - self.total_precedent

    @property
    def est_vide(self) -> bool:
        return self.total_precedent == 0 and not any(self.par_mois)


@dataclass
class LigneCompteAnnuel:
    compte: Compte
    solde_debut: Decimal
    # Solde en fin de chaque mois ; None pour les mois à venir.
    fins_de_mois: list[Decimal | None]

    @property
    def solde_fin(self) -> Decimal:
        connus = [solde for solde in self.fins_de_mois if solde is not None]
        return connus[-1] if connus else self.solde_debut

    @property
    def variation(self) -> Decimal:
        return self.solde_fin - self.solde_debut


@dataclass
class RecapAnnuel:
    annee: int
    mois: list[date]
    flux_par_mois: list[Flux]
    total: Flux
    total_precedent: Flux
    depenses: list[LigneRecap]
    revenus: list[LigneRecap]
    # Opérations sans catégorie, mois par mois.
    revenus_non_classes: list[Decimal]
    depenses_non_classees: list[Decimal]
    comptes: list[LigneCompteAnnuel]

    @property
    def total_revenus_non_classes(self) -> Decimal:
        return sum(self.revenus_non_classes, ZERO)

    @property
    def total_depenses_non_classees(self) -> Decimal:
        return sum(self.depenses_non_classees, ZERO)

    @property
    def patrimoine_debut(self) -> Decimal:
        return sum((ligne.solde_debut for ligne in self.comptes), ZERO)

    @property
    def patrimoine_fin(self) -> Decimal:
        return sum((ligne.solde_fin for ligne in self.comptes), ZERO)

    @property
    def variation_du_patrimoine(self) -> Decimal:
        return self.patrimoine_fin - self.patrimoine_debut


def _additionner(mouvements: list[MouvementsParCategorie]) -> MouvementsParCategorie:
    total: MouvementsParCategorie = {}
    for du_mois in mouvements:
        for categorie_id, (entrees, sorties) in du_mois.items():
            deja = total.get(categorie_id, (ZERO, ZERO))
            total[categorie_id] = (deja[0] + entrees, deja[1] + sorties)
    return total


def _lignes_recap(
    categories: list[Categorie],
    de_l_annee: list[MouvementsParCategorie],
    de_l_annee_precedente: MouvementsParCategorie,
) -> list[LigneRecap]:
    def ligne_feuille(categorie: Categorie) -> LigneRecap:
        return LigneRecap(
            categorie=categorie,
            par_mois=[
                montant_realise(categorie.nature, du_mois.get(categorie.pk, (ZERO, ZERO)))
                for du_mois in de_l_annee
            ],
            total_precedent=montant_realise(
                categorie.nature, de_l_annee_precedente.get(categorie.pk, (ZERO, ZERO))
            ),
        )

    enfants: dict[int, list[Categorie]] = {}
    for categorie in categories:
        if categorie.parent_id is not None:
            enfants.setdefault(categorie.parent_id, []).append(categorie)

    lignes = []
    for parente in (c for c in categories if c.parent_id is None):
        sous_lignes = [ligne_feuille(enfant) for enfant in enfants.get(parente.pk, [])]
        sous_lignes = [s for s in sous_lignes if not (s.categorie.est_archivee and s.est_vide)]
        ligne = LigneRecap(
            categorie=parente,
            par_mois=[sum((s.par_mois[i] for s in sous_lignes), ZERO) for i in range(12)],
            total_precedent=sum((s.total_precedent for s in sous_lignes), ZERO),
            sous_lignes=sous_lignes,
        )
        if not (parente.est_archivee and ligne.est_vide):
            lignes.append(ligne)
    return lignes


def _lignes_par_compte(foyer: Foyer, annee: int, aujourd_hui: date) -> list[LigneCompteAnnuel]:
    soldes_debut = soldes_des_comptes(foyer, date(annee - 1, 12, 31))
    fins_de_mois: list[dict[int, Decimal] | None] = [
        soldes_des_comptes(foyer, min(dernier_du_mois(annee, mois), aujourd_hui))
        if date(annee, mois, 1) <= aujourd_hui
        else None
        for mois in MOIS
    ]
    lignes = []
    for compte in Compte.objects.du_foyer(foyer):
        ligne = LigneCompteAnnuel(
            compte=compte,
            solde_debut=soldes_debut[compte.pk],
            fins_de_mois=[soldes[compte.pk] if soldes else None for soldes in fins_de_mois],
        )
        if not compte.est_archive or ligne.variation != 0:
            lignes.append(ligne)
    return lignes


def recap_annuel(foyer: Foyer, annee: int, aujourd_hui: date | None = None) -> RecapAnnuel:
    """Récapitulatif de l'année, calculé à partir des opérations, comparé à N−1."""
    aujourd_hui = aujourd_hui or date.today()
    par_mois = mouvements_par_mois(foyer, date(annee - 1, 1, 1), date(annee, 12, 31))
    de_l_annee = [par_mois.get((annee, mois), {}) for mois in MOIS]
    de_l_annee_precedente = _additionner([par_mois.get((annee - 1, mois), {}) for mois in MOIS])

    categories = list(Categorie.objects.du_foyer(foyer))
    natures = {categorie.pk: categorie.nature for categorie in categories}
    lignes = _lignes_recap(categories, de_l_annee, de_l_annee_precedente)
    return RecapAnnuel(
        annee=annee,
        mois=[date(annee, mois, 1) for mois in MOIS],
        flux_par_mois=[calculer_flux(du_mois, natures) for du_mois in de_l_annee],
        total=calculer_flux(_additionner(de_l_annee), natures),
        total_precedent=calculer_flux(de_l_annee_precedente, natures),
        depenses=[ligne for ligne in lignes if ligne.categorie.nature == Nature.DEPENSE],
        revenus=[ligne for ligne in lignes if ligne.categorie.nature == Nature.REVENU],
        revenus_non_classes=[du_mois.get(None, (ZERO, ZERO))[0] for du_mois in de_l_annee],
        depenses_non_classees=[-du_mois.get(None, (ZERO, ZERO))[1] for du_mois in de_l_annee],
        comptes=_lignes_par_compte(foyer, annee, aujourd_hui),
    )
