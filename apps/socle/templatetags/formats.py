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
