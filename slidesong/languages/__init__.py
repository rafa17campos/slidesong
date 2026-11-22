"""The languages Slidesong knows: one module per language (en.py, es.py…), found on their own.

A language module says how songs in it are read (common words to detect it, months, seasons, things a line names,
countries, place stop words, Suno section words) and, when it is also an interface language, how the server's
messages read in it (TEXTS, WORDS, LEGACY). en.py is the reference: copy it as <code>.py to add one.
"""
import importlib
import pkgutil

ALL = {}
for _m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    if not _m.name.startswith("_"):
        _mod = importlib.import_module(f"{__name__}.{_m.name}")
        ALL[_mod.CODE] = _mod

# languages the server's messages can be shown in: English (the source) and any with translations
INTERFACE = ["en"] + sorted(c for c, m in ALL.items() if c != "en" and getattr(m, "TEXTS", None))
