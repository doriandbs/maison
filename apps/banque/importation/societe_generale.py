"""Export CSV de l'espace client Société Générale.

    00050397625;10/10/2026;10/11/2026;64;10/11/2026;33823.67 EUR
                         (compte ; début ; fin ; nombre ; date du solde ; solde)
    (ligne vide)
    Date de l'opération;Libellé;Détail de l'écriture;Montant de l'opération;Devise
    06/11/2026;CARTE X2706 05/11 ;CARTE X2706 05/11 SNCF-VOYAGEURS COMMERCE …;-78,00;EUR

Le « Libellé » est tronqué à 18 caractères : on reconstruit un libellé lisible à partir du
« Détail de l'écriture », conservé tel quel dans `libelle_banque`.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from . import ErreurImport, LigneReleve, Releve

NOM = "Société Générale (CSV)"
ENTETE = "date de l'opération;libellé;détail de l'écriture;montant de l'opération"

# (motif sur le détail, gabarit du libellé). Le groupe « tiers » est la contrepartie.
MOTIFS: list[tuple[re.Pattern[str], str]] = [
    (
        # À l'étranger : « OPENAI 34,42 EUR ETATS-UNIS D'AME » → « OPENAI ». Sans cela chaque
        # commande Uber Eats aurait un libellé différent et aucune règle ne les couvrirait.
        re.compile(
            r"^CARTE X\d{4} \d{2}/\d{2} (?:RETRAIT DAB )?(?P<tiers>.+?)"
            r"(?: \d+,\d{2} [A-Z]{3}\b.*| COMMERCE ELECTRONIQUE.*| \d{6,}\w*)?$"
        ),
        "{tiers}",
    ),
    (
        # « … DE: AXA ID: … », ou pour l'impôt « … POUR CPTE DE:DGFIP IMPOT 078 ID: … ».
        re.compile(
            r"^(?:PRELEVEMENT|PRLV) EUROPEEN(?: ACC)? \S+(?: POUR CPTE)? DE: ?(?P<tiers>.+?)"
            r"(?: \d+)? ID:"
        ),
        "Prélèvement – {tiers}",
    ),
    (
        re.compile(r"^VIR(?: INST)? RE(?:CU)? \S+ DE: (?P<tiers>.+?)(?: DATE:| MOTIF:|$)"),
        "Virement reçu – {tiers}",
    ),
    (
        re.compile(r"^\d* ?VIR (?:EUROPEEN|INSTANTANE) EMIS \S+ POUR: (?P<tiers>.+?)(?: \d|$)"),
        "Virement émis – {tiers}",
    ),
    (re.compile(r"^(?P<tiers>ECHEANCE PRET)\b"), "Échéance de prêt"),
    (
        re.compile(
            r"^VIREMENT (?:EMIS|RECU) PAR SOCIETE GENERALE POUR (?P<tiers>TRANSFERT DU SOLDE)"
        ),
        "Transfert du solde (changement d'agence)",
    ),
    (
        re.compile(r"^(?P<tiers>FRAIS PAIEMENT HORS ZONE EURO)\b"),
        "Frais de paiement hors zone euro",
    ),
]


def reconnait(texte: str) -> bool:
    return any(ligne.strip().lower().startswith(ENTETE) for ligne in texte.splitlines()[:5])


def _montant(texte: str) -> Decimal:
    nettoye = texte.replace("\xa0", "").replace(" ", "").replace("EUR", "").replace(",", ".")
    try:
        return Decimal(nettoye)
    except InvalidOperation as erreur:
        raise ErreurImport(f"Montant illisible : « {texte} ».") from erreur


def _date(texte: str) -> date:
    try:
        return datetime.strptime(texte.strip(), "%d/%m/%Y").date()
    except ValueError as erreur:
        raise ErreurImport(f"Date illisible : « {texte} ».") from erreur


def libelle_lisible(detail: str) -> tuple[str, str]:
    """(libellé, tiers) à partir du détail de l'écriture."""
    detail = " ".join(detail.split())
    for motif, gabarit in MOTIFS:
        if trouve := motif.search(detail):
            tiers = trouve.group("tiers").strip(" -")
            return gabarit.format(tiers=tiers)[:200], tiers
    # Inconnu : on retire les longues références numériques de fin, illisibles.
    libelle = re.sub(r"(?: \S*\d{6,}\S*)+$", "", detail) or detail
    return libelle[:200], libelle[:100]


def _premiere_ligne(ligne: str) -> tuple[Decimal | None, date | None]:
    """Solde annoncé par la banque : « compte;début;fin;nombre;date du solde;solde EUR »."""
    champs = ligne.split(";")
    if len(champs) < 6 or "EUR" not in champs[5]:
        return None, None
    try:
        return _montant(champs[5]), _date(champs[4])
    except ErreurImport:
        return None, None


def lire(texte: str) -> Releve:
    lignes_texte = texte.splitlines()
    rang_entete = next(
        i for i, ligne in enumerate(lignes_texte) if ligne.strip().lower().startswith(ENTETE)
    )
    solde, date_solde = _premiere_ligne(lignes_texte[0]) if rang_entete else (None, None)

    lignes: list[LigneReleve] = []
    for numero, champs in enumerate(
        csv.reader(lignes_texte[rang_entete + 1 :], delimiter=";"), start=rang_entete + 2
    ):
        if not champs or not "".join(champs).strip():
            continue
        if len(champs) < 4:
            raise ErreurImport(f"Ligne {numero} incomplète.")
        if len(champs) > 4 and champs[4].strip() not in ("", "EUR"):
            raise ErreurImport(f"Ligne {numero} : seules les opérations en euros sont acceptées.")
        detail = champs[2].strip() or champs[1].strip()
        libelle, tiers = libelle_lisible(detail)
        lignes.append(
            LigneReleve(
                date=_date(champs[0]),
                montant=_montant(champs[3]),
                libelle=libelle,
                tiers=tiers,
                libelle_banque=" ".join(detail.split()),
            )
        )
    return Releve(banque=NOM, lignes=lignes, solde=solde, date_solde=date_solde)
