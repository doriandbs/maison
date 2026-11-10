"""Icônes SVG intégrées dans la page : pas de requête ni de police d'icônes.

Tracés repris du jeu Lucide (https://lucide.dev, licence ISC).
Usage : {% load icones %} … {% icone "accueil" %} ou {% icone "plus" classe="size-4" %}.
"""

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

register = template.Library()

TRACES = {
    "accueil": '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/>'
    '<path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9'
    'a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "comptes": '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4'
    'h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    "operations": '<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/>'
    '<path d="M20 17H4"/>',
    "budget": '<path d="M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055-.998.398'
    '-.998.95v8a1 1 0 0 0 1 1z"/><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>',
    "documents": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
    '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/>'
    '<path d="M16 17H8"/>',
    "categories": '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586'
    ' 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/>'
    '<circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    "membres": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
    '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "deconnexion": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
    '<path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "chevron-bas": '<path d="m6 9 6 6 6-6"/>',
    "chevron-gauche": '<path d="m15 18-6-6 6-6"/>',
    "chevron-droite": '<path d="m9 18 6-6-6-6"/>',
    "menu": '<path d="M4 12h16"/><path d="M4 6h16"/><path d="M4 18h16"/>',
    "fermer": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "valider": '<path d="M20 6 9 17l-5-5"/>',
    "alerte": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
    '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "trombone": '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84'
    'l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    "hausse": '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "baisse": '<path d="m22 17-8.5-8.5-5 5L2 7"/><path d="M16 17h6v-6"/>',
    "calendrier": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/>'
    '<path d="M8 2v4"/><path d="M3 10h18"/>',
    "telecharger": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>'
    '<path d="M12 15V3"/>',
    "ouvrir": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/>'
    '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "modifier": '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83'
    'l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
    "supprimer": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>'
    '<path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    "rechercher": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "foyer": '<path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>'
    '<path d="M9 21v-6h6v6"/>',
}


@register.simple_tag
def icone(nom: str, classe: str = "size-5") -> SafeString:
    """Icône décorative : masquée aux lecteurs d'écran, le texte voisin porte le sens."""
    return format_html(
        '<svg class="{}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true" focusable="false">{}</svg>',
        classe,
        mark_safe(TRACES[nom]),  # noqa: S308 – tracés constants définis ci-dessus
    )
