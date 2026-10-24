"""Traducciones de la aplicación (gettext, con fallback al español)."""
from __future__ import annotations

import gettext

_translation = gettext.translation("gnome-rgb", fallback=True)

_ = _translation.gettext
ngettext = _translation.ngettext


def plural(count: int, singular: str, plural_form: str) -> str:
    """Cadena plural ya formateada, sin concatenar fragmentos traducidos."""
    return ngettext(singular, plural_form, count) % {"count": count}
