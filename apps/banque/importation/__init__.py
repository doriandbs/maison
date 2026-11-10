"""Lecture des relevés bancaires exportés depuis l'espace client de la banque.

Chaque format est un module qui expose `NOM`, `reconnait(texte)` et `lire(texte)`.
Ajouter une banque = ajouter un module à `FORMATS`, sans toucher au reste.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

TAILLE_MAX = 2 * 1024 * 1024
LIGNES_MAX = 5000


class ErreurImport(ValueError):
    pass


@dataclass(frozen=True)
class LigneReleve:
    date: date
    montant: Decimal
    libelle: str
    # Contrepartie (commerçant, émetteur d'un prélèvement…) : motif proposé pour une règle.
    tiers: str
    libelle_banque: str


@dataclass(frozen=True)
class Releve:
    banque: str
    lignes: list[LigneReleve]
    solde: Decimal | None = None
    date_solde: date | None = None


def vers_session(releve: Releve) -> dict[str, Any]:
    """Relevé sérialisable en JSON, conservé côté serveur entre le dépôt et la validation."""
    return {
        "banque": releve.banque,
        "solde": str(releve.solde) if releve.solde is not None else None,
        "date_solde": releve.date_solde.isoformat() if releve.date_solde else None,
        "lignes": [
            [
                ligne.date.isoformat(),
                str(ligne.montant),
                ligne.libelle,
                ligne.tiers,
                ligne.libelle_banque,
            ]
            for ligne in releve.lignes
        ],
    }


def depuis_session(donnees: dict[str, Any]) -> Releve:
    return Releve(
        banque=donnees["banque"],
        solde=Decimal(donnees["solde"]) if donnees["solde"] is not None else None,
        date_solde=date.fromisoformat(donnees["date_solde"]) if donnees["date_solde"] else None,
        lignes=[
            LigneReleve(date.fromisoformat(jour), Decimal(montant), libelle, tiers, banque)
            for jour, montant, libelle, tiers, banque in donnees["lignes"]
        ],
    )


def _decoder(contenu: bytes) -> str:
    # Les banques françaises exportent souvent en Latin-1 (Windows-1252), parfois en UTF-8.
    try:
        return contenu.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenu.decode("cp1252", errors="replace")


def lire_releve(contenu: bytes) -> Releve:
    from . import societe_generale

    formats = [societe_generale]
    if len(contenu) > TAILLE_MAX:
        raise ErreurImport("Le fichier dépasse 2 Mo.")
    texte = _decoder(contenu)
    for module in formats:
        if module.reconnait(texte):
            releve = module.lire(texte)
            if not releve.lignes:
                raise ErreurImport("Le relevé ne contient aucune opération.")
            if len(releve.lignes) > LIGNES_MAX:
                raise ErreurImport(f"Le relevé dépasse {LIGNES_MAX} opérations.")
            return releve
    noms = ", ".join(module.NOM for module in formats)
    raise ErreurImport(f"Format de fichier non reconnu. Formats acceptés : {noms}.")
