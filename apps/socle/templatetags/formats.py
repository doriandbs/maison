from decimal import Decimal

from django import template

register = template.Library()

ESPACE_FINE_INSECABLE = " "
ESPACE_INSECABLE = " "


@register.filter
def euros(valeur: Decimal | int | None) -> str:
    """1234.5 → « 1 234,50 € » (espaces insécables)."""
    if valeur is None:
        return ""
    texte = f"{valeur:,.2f}".replace(",", ESPACE_FINE_INSECABLE).replace(".", ",")
    return f"{texte}{ESPACE_INSECABLE}€"


@register.filter
def euros_ou_vide(valeur: Decimal | int | None) -> str:
    """Comme `euros`, mais laisse la cellule vide pour un montant nul (tableaux denses)."""
    return euros(valeur) if valeur else ""


@register.filter
def pourcent(valeur: Decimal | None) -> str:
    """12.5 → « 12,5 % » ; « – » quand le taux est indéfini."""
    if valeur is None:
        return "–"
    return f"{valeur:.1f}".replace(".", ",") + f"{ESPACE_INSECABLE}%"


@register.filter
def nombre_brut(valeur: Decimal | int) -> str:
    """Nombre au format informatique (point décimal) pour un attribut HTML."""
    return f"{max(valeur, 0):.2f}"


@register.filter
def valeur_brute(valeur: Decimal | int | None) -> str:
    """Comme `nombre_brut` mais signé : valeur d'arrivée des compteurs animés."""
    return f"{valeur or 0:.2f}"


@register.filter
def part_de(valeur: Decimal | int | None, total: Decimal | int | None) -> str:
    """Part de `valeur` dans `total`, en pourcentage borné à 0–100, pour une jauge CSS."""
    if not total or total <= 0 or not valeur:
        return "0%"
    part = min(max(Decimal(valeur) / Decimal(total) * 100, Decimal(0)), Decimal(100))
    return f"{part:.1f}%"
