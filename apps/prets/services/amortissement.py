"""Tableau d'amortissement d'un prêt à taux fixe, mensualités constantes.

Fonctions pures, sans base de données : tout ce qu'affiche l'onglet Crédits en découle
(capital restant dû, coût total, date de fin, simulation de remboursement anticipé).

Conventions, celles des banques françaises :
- intérêts du mois = capital restant dû × taux annuel / 12, arrondis au centime ;
- mensualité (hors assurance) arrondie au centime ; la dernière solde le capital ;
- assurance : montant mensuel fixe, dû à chaque échéance, différé compris ;
- différé partiel : on paie les intérêts, le capital ne bouge pas ;
- différé total : on ne paie que l'assurance, les intérêts s'ajoutent au capital ;
- un remboursement anticipé s'impute avant l'échéance qui suit sa date.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
CENTIME = Decimal("0.01")


class Differe:
    AUCUN = "aucun"
    PARTIEL = "partiel"
    TOTAL = "total"


class Effet:
    """Ce que réduit un remboursement anticipé."""

    DUREE = "duree"
    MENSUALITE = "mensualite"


@dataclass(frozen=True)
class Conditions:
    capital: Decimal
    taux_annuel: Decimal  # en %, ex. Decimal("3.45")
    duree_mois: int  # durée totale, différé compris
    premiere_echeance: date
    assurance_mensuelle: Decimal = ZERO
    differe_mois: int = 0
    type_differe: str = Differe.AUCUN


@dataclass(frozen=True)
class Anticipe:
    date: date
    montant: Decimal
    effet: str = Effet.DUREE


@dataclass(frozen=True)
class Echeance:
    numero: int
    date: date
    capital_debut: Decimal  # après un éventuel remboursement anticipé
    interets: Decimal
    amortissement: Decimal  # négatif en différé total : les intérêts s'ajoutent au capital
    assurance: Decimal
    anticipe: Decimal = ZERO  # remboursement anticipé imputé juste avant cette échéance
    en_differe: bool = False

    @property
    def mensualite(self) -> Decimal:
        """Somme prélevée hors assurance."""
        return self.interets + self.amortissement

    @property
    def total(self) -> Decimal:
        return self.mensualite + self.assurance

    @property
    def capital_fin(self) -> Decimal:
        return self.capital_debut - self.amortissement


@dataclass
class Tableau:
    conditions: Conditions
    echeances: list[Echeance] = field(default_factory=list)
    anticipes: list[Anticipe] = field(default_factory=list)

    @property
    def total_interets(self) -> Decimal:
        return sum((e.interets for e in self.echeances), ZERO)

    @property
    def total_assurance(self) -> Decimal:
        return sum((e.assurance for e in self.echeances), ZERO)

    @property
    def cout_total(self) -> Decimal:
        """Coût du crédit : intérêts et assurance, hors frais de dossier et de garantie."""
        return self.total_interets + self.total_assurance

    @property
    def date_fin(self) -> date | None:
        return self.echeances[-1].date if self.echeances else None

    @property
    def mensualite_amortissement(self) -> Decimal | None:
        """Mensualité de la première échéance hors différé (hors assurance)."""
        return next((e.mensualite for e in self.echeances if not e.en_differe), None)

    def capital_restant_du(self, a_date: date) -> Decimal:
        """Capital dû après les échéances et remboursements datés au plus tard de ce jour."""
        capital = self.conditions.capital
        for anticipe in self.anticipes:
            if anticipe.date <= a_date:
                capital -= anticipe.montant
        for echeance in self.echeances:
            if echeance.date <= a_date:
                capital -= echeance.amortissement
        return max(capital, ZERO)

    def echeances_restantes(self, a_date: date) -> int:
        return sum(1 for e in self.echeances if e.date > a_date)

    def mensualite_en_cours(self, a_date: date) -> Decimal | None:
        """Total (assurance comprise) de la prochaine échéance."""
        return next((e.total for e in self.echeances if e.date > a_date), None)


def arrondir(montant: Decimal) -> Decimal:
    return montant.quantize(CENTIME, rounding=ROUND_HALF_UP)


def ajouter_mois(depart: date, mois: int) -> date:
    """Même quantième, ramené au dernier jour du mois si besoin (31 janv. + 1 → 28/29 févr.)."""
    rang = depart.year * 12 + depart.month - 1 + mois
    annee, numero = divmod(rang, 12)
    dernier_jour = calendar.monthrange(annee, numero + 1)[1]
    return date(annee, numero + 1, min(depart.day, dernier_jour))


def mensualite_constante(capital: Decimal, taux_annuel: Decimal, mois: int) -> Decimal:
    """Mensualité hors assurance qui rembourse `capital` en `mois` échéances."""
    if mois <= 0:
        return arrondir(capital)
    taux = taux_annuel / Decimal(1200)
    if taux == 0:
        return arrondir(capital / mois)
    return arrondir(capital * taux / (1 - (1 + taux) ** -mois))


def calculer(
    conditions: Conditions, anticipes: list[Anticipe] | tuple[Anticipe, ...] = ()
) -> Tableau:
    taux = conditions.taux_annuel / Decimal(1200)
    a_imputer = sorted(anticipes, key=lambda a: a.date)
    imputes: list[Anticipe] = []
    capital = conditions.capital
    mensualite: Decimal | None = None  # calculée à la première échéance amortissable
    echeances: list[Echeance] = []

    for numero in range(1, conditions.duree_mois + 1):
        jour = ajouter_mois(conditions.premiere_echeance, numero - 1)

        anticipe = ZERO
        while a_imputer and a_imputer[0].date < jour:
            remboursement = a_imputer.pop(0)
            montant = min(remboursement.montant, capital)
            if montant <= 0:
                continue
            capital -= montant
            anticipe += montant
            imputes.append(Anticipe(remboursement.date, montant, remboursement.effet))
            if remboursement.effet == Effet.MENSUALITE:
                mensualite = None  # recalculée sur la durée restante
        if capital <= 0:
            break

        interets = arrondir(capital * taux)
        en_differe = numero <= conditions.differe_mois
        if en_differe:
            # Partiel : on paie les intérêts. Total : ils s'ajoutent au capital.
            capitalises = conditions.type_differe == Differe.TOTAL
            amortissement = -interets if capitalises else ZERO
        else:
            if mensualite is None:
                restantes = conditions.duree_mois - numero + 1
                mensualite = mensualite_constante(capital, conditions.taux_annuel, restantes)
            amortissement = mensualite - interets
            if amortissement >= capital or numero == conditions.duree_mois:
                amortissement = capital

        echeances.append(
            Echeance(
                numero=numero,
                date=jour,
                capital_debut=capital,
                interets=interets,
                amortissement=amortissement,
                assurance=conditions.assurance_mensuelle,
                anticipe=anticipe,
                en_differe=en_differe,
            )
        )
        capital -= amortissement
        if capital <= 0:
            break

    return Tableau(conditions=conditions, echeances=echeances, anticipes=imputes)


@dataclass(frozen=True)
class Simulation:
    avant: Tableau
    apres: Tableau
    a_date: date

    @property
    def economie_interets(self) -> Decimal:
        return self.avant.total_interets - self.apres.total_interets

    @property
    def economie_assurance(self) -> Decimal:
        return self.avant.total_assurance - self.apres.total_assurance

    @property
    def mois_gagnes(self) -> int:
        return len(self.avant.echeances) - len(self.apres.echeances)

    @property
    def mensualite_avant(self) -> Decimal | None:
        return self.avant.mensualite_en_cours(self.a_date)

    @property
    def mensualite_apres(self) -> Decimal | None:
        return self.apres.mensualite_en_cours(self.a_date)


def simuler(conditions: Conditions, deja: list[Anticipe], hypothese: Anticipe) -> Simulation:
    """Compare le prêt tel qu'il est avec le même prêt et un remboursement de plus.

    Hors indemnités de remboursement anticipé (au plus 6 mois d'intérêts ou 3 % du capital
    remboursé), à voir dans l'offre de prêt.
    """
    return Simulation(
        avant=calculer(conditions, deja),
        apres=calculer(conditions, [*deja, hypothese]),
        a_date=hypothese.date,
    )
