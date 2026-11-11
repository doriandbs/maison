"""Import d'un relevé dans un compte : aperçu (doublons, catégories proposées) puis
enregistrement des lignes retenues."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from apps.banque.importation import Releve
from apps.banque.models import Categorie, Compte, Operation
from apps.banque.services.regles import Classeur, normaliser
from apps.banque.services.soldes import soldes_des_comptes
from apps.foyers.models import Foyer
from apps.socle.perimetre import Perimetre
from apps.utilisateurs.models import Utilisateur

ZERO = Decimal("0.00")


class Statut:
    NOUVELLE = "nouvelle"
    # Même date et même montant qu'une opération déjà présente (saisie à la main…).
    DOUBLON_POSSIBLE = "doublon_possible"
    # Exactement la même ligne de relevé, déjà importée : jamais réimportée.
    DEJA_IMPORTEE = "deja_importee"
    # Au plus tard à la date du solde initial : déjà comprise dans ce solde.
    ANTERIEURE = "anterieure"
    IMPORTABLES = frozenset({NOUVELLE, DOUBLON_POSSIBLE})


@dataclass
class LigneApercu:
    rang: int
    date: date
    montant: Decimal
    libelle: str
    tiers: str
    libelle_banque: str
    empreinte: str
    statut: str
    categorie: Categorie | None

    @property
    def importable(self) -> bool:
        return self.statut in Statut.IMPORTABLES

    @property
    def cochee_par_defaut(self) -> bool:
        return self.statut == Statut.NOUVELLE


@dataclass
class Apercu:
    compte: Compte
    lignes: list[LigneApercu]
    solde_banque: Decimal | None
    date_solde: date | None
    solde_calcule: Decimal | None

    def compter(self, statut: str) -> int:
        return sum(1 for ligne in self.lignes if ligne.statut == statut)

    @property
    def anterieures(self) -> list[LigneApercu]:
        return [ligne for ligne in self.lignes if ligne.statut == Statut.ANTERIEURE]

    @property
    def nouveau_debut(self) -> date | None:
        """Date de départ qui rendrait importables les lignes antérieures."""
        if not self.anterieures or self.compte.est_valorise:
            return None
        return min(ligne.date for ligne in self.anterieures) - timedelta(days=1)

    @property
    def ecart(self) -> Decimal | None:
        if self.solde_banque is None or self.solde_calcule is None:
            return None
        return self.solde_banque - self.solde_calcule


def _empreinte(compte: Compte, jour: date, montant: Decimal, texte: str, rang: int) -> str:
    """Identique pour la même ligne d'un relevé à l'autre. Le rang distingue deux lignes
    strictement identiques le même jour (deux cafés au même endroit)."""
    source = f"{compte.pk}|{jour.isoformat()}|{montant}|{normaliser(texte)}|{rang}"
    return hashlib.sha256(source.encode()).hexdigest()


def _empreintes_importees(compte: Compte) -> set[str]:
    empreintes = (
        Operation.objects.filter(compte=compte)
        .exclude(empreinte_import=None)
        .values_list("empreinte_import", flat=True)
    )
    return {empreinte for empreinte in empreintes if empreinte}


def preparer(compte: Compte, releve: Releve, classement: Foyer | Perimetre | None = None) -> Apercu:
    """`classement` : où chercher les règles (le foyer courant) ; par défaut, l'espace du compte."""
    deja_importees = _empreintes_importees(compte)
    date_et_montant = set(Operation.objects.filter(compte=compte).values_list("date", "montant"))
    classeur = Classeur(classement or compte.foyer)

    vues: Counter[tuple[date, Decimal, str]] = Counter()
    lignes: list[LigneApercu] = []
    for rang, ligne in enumerate(releve.lignes):
        cle = (ligne.date, ligne.montant, normaliser(ligne.libelle_banque))
        vues[cle] += 1
        empreinte = _empreinte(compte, ligne.date, ligne.montant, ligne.libelle_banque, vues[cle])
        if empreinte in deja_importees:
            statut = Statut.DEJA_IMPORTEE
        elif ligne.date <= compte.ouvert_le:
            statut = Statut.ANTERIEURE
        elif (ligne.date, ligne.montant) in date_et_montant:
            statut = Statut.DOUBLON_POSSIBLE
        else:
            statut = Statut.NOUVELLE
        lignes.append(
            LigneApercu(
                rang=rang,
                date=ligne.date,
                montant=ligne.montant,
                libelle=ligne.libelle,
                tiers=ligne.tiers,
                libelle_banque=ligne.libelle_banque,
                empreinte=empreinte,
                statut=statut,
                categorie=classeur.categorie(ligne.libelle, ligne.libelle_banque),
            )
        )
    return Apercu(
        compte=compte,
        lignes=lignes,
        solde_banque=releve.solde,
        date_solde=releve.date_solde,
        solde_calcule=_solde_apres_import(compte, lignes, releve.date_solde),
    )


def _solde_apres_import(
    compte: Compte, lignes: list[LigneApercu], date_solde: date | None
) -> Decimal | None:
    """Solde que Maison calculerait à la date du relevé si toutes les nouvelles lignes
    étaient importées : s'il diffère de celui de la banque, il manque quelque chose."""
    if date_solde is None or compte.est_valorise:
        return None
    actuel = soldes_des_comptes(compte.foyer, date_solde)[compte.pk]
    ajout = sum(
        (
            ligne.montant
            for ligne in lignes
            if ligne.statut == Statut.NOUVELLE and ligne.date <= date_solde
        ),
        ZERO,
    )
    return actuel + ajout


@transaction.atomic
def avancer_le_debut(apercu: Apercu) -> None:
    """Fait démarrer le compte la veille de la plus ancienne ligne antérieure.

    Le solde initial est diminué de ces lignes : une fois importées, le solde
    d'aujourd'hui reste exactement le même, mais l'historique est complet.
    """
    nouveau_debut = apercu.nouveau_debut
    if nouveau_debut is None:
        return
    compte = Compte.objects.select_for_update().get(pk=apercu.compte.pk)
    compte.solde_initial -= sum((ligne.montant for ligne in apercu.anterieures), ZERO)
    compte.ouvert_le = nouveau_debut
    compte.save(update_fields=["solde_initial", "ouvert_le", "modifie_le"])


@dataclass(frozen=True)
class Choix:
    ligne: LigneApercu
    categorie: Categorie | None


@transaction.atomic
def enregistrer(compte: Compte, choix: list[Choix], cree_par: Utilisateur) -> int:
    """Crée les opérations retenues ; une ligne déjà importée entre-temps est ignorée."""
    deja = _empreintes_importees(compte)
    nouvelles = [
        Operation(
            foyer=compte.foyer,
            compte=compte,
            date=element.ligne.date,
            libelle=element.ligne.libelle,
            libelle_banque=element.ligne.libelle_banque,
            montant=element.ligne.montant,
            categorie=element.categorie,
            empreinte_import=element.ligne.empreinte,
            cree_par=cree_par,
        )
        for element in choix
        if element.ligne.importable
        and element.ligne.empreinte not in deja
        and element.ligne.montant != 0
        and element.ligne.date > compte.ouvert_le
    ]
    Operation.objects.bulk_create(nouvelles)
    return len(nouvelles)
