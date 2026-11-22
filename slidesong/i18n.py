"""Server texts in the language of whoever asked (Accept-Language): English by default, or any interface language
in slidesong/languages/ (a module with TEXTS).

- Messages are written in English in the code and translated on the way out: `tr("Project not found")`,
  `tr("change the photo of shot {n}", n=4)`. The request's language lives in a context variable set by a middleware
  (`use()`); background jobs run with the language of the request that started them (`in_context`).
- Texts that are stored (undo labels, the «why» chips of a photo, transition reasons, job errors) are kept as they
  were made and shown through `localize()`, which reads them back to English with the tables of every language and
  then writes them in the language asked. So a project made in Spanish reads in English and the other way round,
  older texts included.
"""
import contextvars
import re
import threading
from functools import lru_cache

from .languages import ALL, INTERFACE

LANG: contextvars.ContextVar[str] = contextvars.ContextVar("lang", default="en")


def use(accept_language: str | None):
    """Set the language from an Accept-Language header ("es", "es-ES,es;q=0.9,en;q=0.8"…): the first one this server
    speaks, else English."""
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower().split("-")[0]
        if code in INTERFACE:
            LANG.set(code)
            return
    LANG.set("en")


def lang() -> str:
    return LANG.get()


def in_context(fn):
    """A function that runs with the current language (for threads: they start with an empty context)."""
    ctx = contextvars.copy_context()
    return lambda *a, **k: ctx.run(fn, *a, **k)


def thread(target, **kw) -> threading.Thread:
    """threading.Thread whose target keeps the language of the request that started it."""
    return threading.Thread(target=in_context(target), **kw)


# ---------------- the tables (slidesong/languages/<code>.py) ----------------
TEXTS = {code: dict(getattr(m, "TEXTS", {}) or {}) for code, m in ALL.items() if code != "en"}  # English -> code
WORDS = {code: dict(getattr(m, "WORDS", {}) or {}) for code, m in ALL.items() if code != "en"}  # placeholder values
LEGACY = {code: dict(getattr(m, "LEGACY", {}) or {}) for code, m in ALL.items() if code != "en"}  # old text -> English
_WORDS_EN = {code: {v: k for k, v in w.items()} for code, w in WORDS.items()}  # code -> English

MONTHS_EN = ALL["en"].MONTH_NAMES.split()
JOB_NAME = {"analyze": "Analyzing the song", "suggest": "Choosing photos", "render": "Making the video",
            "export": "Preparing the editable project"}
_AND = {"en": " and ", "es": " y "}


def _word(v: str, target: str) -> str:
    """A placeholder's value in the target language (lists «a, b and c» part by part)."""
    joiners = set(_AND.values())
    out = []
    for p in re.split(r"(, | and | y )", v):
        if p == ", ":
            out.append(p)
        elif p in joiners:
            out.append(_AND.get(target, " and "))
        else:
            en = next((w[p] for w in _WORDS_EN.values() if p in w), p)  # to English first
            out.append(en if target == "en" else WORDS.get(target, {}).get(en, en))
    return "".join(out)


def tr(text: str, **kw) -> str:
    """`text` (English) in the request's language, with its placeholders filled (and translated when known)."""
    target = LANG.get()
    t = text if target == "en" else TEXTS.get(target, {}).get(text, text)
    return t.format(**{k: _word(str(v), target) for k, v in kw.items()}) if kw else t


def _pattern(template: str) -> re.Pattern:
    """«change the photo of shot {n}» -> a regex with a named group per placeholder."""
    out, pos = [], 0
    for m in re.finditer(r"\{(\w+)\}", template):
        out.append(re.escape(template[pos:m.start()]))
        out.append(f"(?P<{m.group(1)}>.+?)")
        pos = m.end()
    out.append(re.escape(template[pos:]))
    return re.compile("".join(out), re.S)


def _specific_first(pairs):
    """The most specific patterns (longest literal part) first."""
    return sorted(pairs, key=lambda x: -len(re.sub(r"\(\?P<\w+>\.\+\?\)", "", x[0].pattern)))


@lru_cache(maxsize=1)
def _tables():
    """(to English from any language, {code: from English to that language})."""
    to_en = _specific_first([(_pattern(tx), en) for code in TEXTS for en, tx in TEXTS[code].items()]
                            + [(_pattern(old), en) for code in LEGACY for old, en in LEGACY[code].items()])
    from_en = {code: _specific_first([(_pattern(en), tx) for en, tx in TEXTS[code].items()]) for code in TEXTS}
    return to_en, from_en


def _fill(m, tmpl, target):
    return tmpl.format(**{k: _word(v, target) for k, v in m.groupdict().items()})


@lru_cache(maxsize=4096)
def _localize(text: str, target: str) -> str:
    to_en, from_en = _tables()
    en = next((_fill(m, tmpl, "en") for pat, tmpl in to_en if (m := pat.fullmatch(text))), text)
    if target == "en":
        return en
    return next((_fill(m, tmpl, target) for pat, tmpl in from_en.get(target, []) if (m := pat.fullmatch(en))), en)


def localize(text):
    """A stored text (in any known language, older ones included) in the request's language; unknown text as is."""
    if not isinstance(text, str) or not text:
        return text
    return _localize(text, LANG.get())
