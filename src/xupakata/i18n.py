"""Traducciones de la aplicación (gettext, con fallback al español)."""
from __future__ import annotations

import gettext
import os
import sys

# Dentro del Snap el catálogo se instala en $SNAP/share/locale.
_locale_dir = os.path.join(os.environ.get("SNAP", sys.prefix), "share", "locale")
_translation = gettext.translation("xupakata", localedir=_locale_dir, fallback=True)

_ = _translation.gettext
ngettext = _translation.ngettext


def plural(count: int, singular: str, plural_form: str) -> str:
    """Cadena plural ya formateada, sin concatenar fragmentos traducidos."""
    return ngettext(singular, plural_form, count) % {"count": count}
