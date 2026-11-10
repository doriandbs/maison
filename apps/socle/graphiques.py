"""Géométrie des graphiques, calculée côté serveur et dessinée en SVG par les gabarits.

Pas de bibliothèque JavaScript : les graphiques s'affichent sans script, se testent en
Python, et le gabarit ne fait que placer les formes calculées ici. Règles de tracé :
traits fins (2 px), aire très claire, grille discrète, un seul axe, barres de 24 px au plus
aux coins arrondis côté valeur.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from apps.socle.templatetags.formats import euros

LARGEUR = 820
HAUTEUR = 240
MARGE_GAUCHE = 56
MARGE_DROITE = 24
MARGE_HAUT = 16
MARGE_BAS = 28
LARGEUR_BARRE_MAX = 24
ECART_BARRES = 2
RAYON_BARRE = 4


def graduations(minimum: float, maximum: float, cible: int = 4) -> list[float]:
    """Valeurs rondes qui encadrent [minimum, maximum] : pas de 1, 2, 2,5 ou 5 × 10ⁿ."""
    if maximum == minimum:
        maximum, minimum = maximum + 1, minimum - 1 if minimum < 0 else 0
    brut = (maximum - minimum) / cible
    puissance = 10 ** math.floor(math.log10(brut))
    pas = next(f * puissance for f in (1, 2, 2.5, 5, 10) if f * puissance >= brut)
    debut = math.floor(minimum / pas) * pas
    fin = math.ceil(maximum / pas) * pas
    nombre = round((fin - debut) / pas)
    return [round(debut + i * pas, 6) for i in range(nombre + 1)]


def euros_compacts(valeur: float) -> str:
    """Étiquette d'axe : « 850 € », « 12 k€ », « 1,2 M€ » (insécables, format français)."""
    absolu = abs(valeur)
    signe = "−" if valeur < 0 else ""
    if absolu >= 1_000_000:
        texte = f"{absolu / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " M€"
    elif absolu >= 1_000:
        texte = f"{absolu / 1_000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " k€"
    else:
        texte = f"{absolu:.0f} €"
    return signe + texte


@dataclass(frozen=True)
class Graduation:
    y: float
    texte: str


@dataclass(frozen=True)
class EtiquetteX:
    x: float
    texte: str


@dataclass(frozen=True)
class Echelle:
    """Passage des valeurs aux ordonnées SVG (l'axe des y descend)."""

    minimum: float
    maximum: float

    def y(self, valeur: float) -> float:
        hauteur_utile = HAUTEUR - MARGE_HAUT - MARGE_BAS
        part = (valeur - self.minimum) / (self.maximum - self.minimum)
        return round(HAUTEUR - MARGE_BAS - part * hauteur_utile, 2)

    def graduations(self, valeurs: list[float]) -> list[Graduation]:
        return [Graduation(self.y(v), euros_compacts(v)) for v in valeurs]


# --- Courbe (une série dans le temps) ------------------------------------------


@dataclass(frozen=True)
class PointCourbe:
    x: float
    y: float
    zone_x: float  # début de la bande de survol (plus large que le point)
    zone_largeur: float
    libelle: str
    valeur: Decimal

    @property
    def infobulle(self) -> str:
        return f"{euros(self.valeur)}\n{self.libelle}"


@dataclass(frozen=True)
class Courbe:
    points: list[PointCourbe]
    chemin: str
    aire: str
    graduations: list[Graduation]
    etiquettes_x: list[EtiquetteX]
    y_zero: float | None  # ligne du zéro si l'axe le traverse
    largeur: int = LARGEUR
    hauteur: int = HAUTEUR
    gauche: int = MARGE_GAUCHE
    droite: int = LARGEUR - MARGE_DROITE
    bas: int = HAUTEUR - MARGE_BAS

    @property
    def dernier(self) -> PointCourbe:
        return self.points[-1]


def courbe(valeurs: list[tuple[str, str, Decimal]]) -> Courbe | None:
    """(libellé long, libellé d'axe, valeur) dans l'ordre chronologique ; None sous 2 points."""
    if len(valeurs) < 2:
        return None
    nombres = [float(v) for _, _, v in valeurs]
    reperes = graduations(min(min(nombres), 0), max(max(nombres), 0))
    echelle = Echelle(reperes[0], reperes[-1])
    pas = (LARGEUR - MARGE_GAUCHE - MARGE_DROITE) / (len(valeurs) - 1)

    points = []
    for rang, (libelle, _, valeur) in enumerate(valeurs):
        x = round(MARGE_GAUCHE + rang * pas, 2)
        points.append(
            PointCourbe(
                x, echelle.y(float(valeur)), round(x - pas / 2, 2), round(pas, 2), libelle, valeur
            )
        )
    chemin = "M" + " L".join(f"{p.x},{p.y}" for p in points)
    base = echelle.y(max(reperes[0], 0))
    aire = f"{chemin} L{points[-1].x},{base} L{points[0].x},{base} Z"
    # Assez d'étiquettes pour se repérer, pas au point de se chevaucher.
    tous_les = max(1, math.ceil(len(valeurs) / 8))
    etiquettes = [
        EtiquetteX(points[rang].x, valeurs[rang][1])
        for rang in range(len(valeurs) - 1, -1, -tous_les)
    ][::-1]
    return Courbe(
        points=points,
        chemin=chemin,
        aire=aire,
        graduations=echelle.graduations(reperes),
        etiquettes_x=etiquettes,
        y_zero=echelle.y(0) if reperes[0] < 0 < reperes[-1] else None,
    )


# --- Histogramme groupé (deux séries par catégorie) -----------------------------


@dataclass(frozen=True)
class Barre:
    x: float
    y: float
    largeur: float
    hauteur: float
    serie: int  # 1 ou 2 : couleur --graphe-1 / --graphe-2

    @property
    def chemin(self) -> str:
        """Rectangle aux coins supérieurs arrondis, carré sur la ligne de base."""
        r = min(RAYON_BARRE, self.hauteur, self.largeur / 2)
        x, y, w, h = self.x, self.y, self.largeur, self.hauteur
        return (
            f"M{x},{y + h} V{y + r} Q{x},{y} {x + r},{y} H{x + w - r} "
            f"Q{x + w},{y} {x + w},{y + r} V{y + h} Z"
        )


@dataclass(frozen=True)
class Groupe:
    zone_x: float
    zone_largeur: float
    barres: list[Barre]
    infobulle: str


@dataclass(frozen=True)
class Histogramme:
    groupes: list[Groupe]
    graduations: list[Graduation]
    etiquettes_x: list[EtiquetteX]
    largeur: int = LARGEUR
    hauteur: int = HAUTEUR
    gauche: int = MARGE_GAUCHE
    droite: int = LARGEUR - MARGE_DROITE
    bas: int = HAUTEUR - MARGE_BAS


def histogramme_groupe(
    categories: list[tuple[str, str]],
    serie_1: list[Decimal | None],
    serie_2: list[Decimal | None],
    noms: tuple[str, str],
) -> Histogramme | None:
    """Deux barres par catégorie : série 2 à gauche (référence), série 1 à droite.

    Une valeur None (mois à venir) ne dessine pas de barre. Valeurs positives seulement.
    """
    presentes = [float(v) for v in [*serie_1, *serie_2] if v is not None]
    if not presentes or max(presentes) <= 0:
        return None
    reperes = graduations(0, max(presentes))
    echelle = Echelle(0, reperes[-1])
    case = (LARGEUR - MARGE_GAUCHE - MARGE_DROITE) / len(categories)
    largeur = min(LARGEUR_BARRE_MAX, (case * 0.7 - ECART_BARRES) / 2)
    bas = HAUTEUR - MARGE_BAS

    groupes = []
    for rang, ((libelle, _), v1, v2) in enumerate(zip(categories, serie_1, serie_2, strict=True)):
        centre = MARGE_GAUCHE + case * (rang + 0.5)
        barres = []
        for serie, valeur, x in (
            (2, v2, centre - ECART_BARRES / 2 - largeur),
            (1, v1, centre + ECART_BARRES / 2),
        ):
            if valeur is not None and valeur > 0:
                y = echelle.y(float(valeur))
                barres.append(Barre(round(x, 2), y, round(largeur, 2), round(bas - y, 2), serie))
        lignes = [libelle] + [
            f"{nom} : {euros(valeur) if valeur is not None else '–'}"
            for nom, valeur in ((noms[0], v1), (noms[1], v2))
        ]
        groupes.append(
            Groupe(round(centre - case / 2, 2), round(case, 2), barres, "\n".join(lignes))
        )
    etiquettes = [
        EtiquetteX(round(MARGE_GAUCHE + case * (rang + 0.5), 2), court)
        for rang, (_, court) in enumerate(categories)
    ]
    return Histogramme(groupes, echelle.graduations(reperes), etiquettes)
