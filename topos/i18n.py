"""Two languages, side by side / Dos idiomas, lado a lado.

Every user-facing string is written as `t("español", "english")`, so both
versions live next to each other and neither can drift silently. The language
comes from TOPOS_LANG, then LC_ALL / LC_MESSAGES / LANG, then the system locale;
anything that is not Spanish falls back to English.

Cada texto para el usuario se escribe `t("español", "english")`: las dos
versiones viven juntas. El idioma sale de TOPOS_LANG, luego de LC_ALL /
LC_MESSAGES / LANG y luego del sistema; lo que no sea español cae en inglés.
"""

import locale
import os

LANGS = ("es", "en")


def lang():
    for var in ("TOPOS_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "").strip().lower()
        if value and value not in ("c", "posix", "c.utf-8"):
            return "es" if value.startswith(("es", "spanish")) else "en"
    try:
        code = (locale.getlocale()[0] or "").lower()
    except ValueError:
        code = ""
    return "es" if code.startswith(("es", "spanish")) else "en"


def t(es, en):
    """El texto en el idioma activo / the text in the active language."""
    return es if lang() == "es" else en


def plural(n, one_es, one_en, many_es=None, many_en=None):
    """'1 deadlock', '3 procesos' — con el número delante."""
    if n == 1:
        return f"{n} {t(one_es, one_en)}"
    return f"{n} {t(many_es or one_es + 's', many_en or one_en + 's')}"
