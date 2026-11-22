"""Understand the lyrics with Claude, in whatever language they are sung: per line an English translation, what a
photo illustrating it would show, a few tags an image tagger would see, and the month or season it names. One call
per song (cents), cached in the project.

Uses ANTHROPIC_API_KEY (or any credential the Anthropic SDK resolves). Without it, or if the call fails, the
local translator fills in the English and the visual description is just that translation.
"""
import os

from pydantic import BaseModel

from . import config, lexicon, translate

MODEL = config.env("LYRICS_MODEL", "claude-sonnet-5-5")

SYSTEM = """You prepare song lyrics for a tool that picks family photos to illustrate each line of a song.
For every numbered line return:
- english: a faithful English translation (keep names as they are).
- visual: what a photo illustrating this line would most likely show, in plain concrete English (scene, objects,
  activity, season), max 15 words, no names. Use the whole song for context: colloquial words, what the family
  is actually doing, figurative lines turned into something photographable.
- tags: up to 4 lowercase English nouns an image tagger would see in such a photo (e.g. "puddle", "birthday cake").
- month: the calendar month (1-12) the line names, or null. Only an explicit month, not a guess.
- season: "summer", "autumn", "winter", "spring" or "christmas" if the line names one, else null.
Return every line, in order."""


class Line(BaseModel):
    n: int
    english: str
    visual: str
    tags: list[str]
    month: int | None = None
    season: str | None = None


class Result(BaseModel):
    lines: list[Line]


def _local(lines, lang=None):
    try:
        if lang == "en":
            en = list(lines)
        else:
            en = translate.to_english(lines, lang) if translate.available(lang=lang) else [""] * len(lines)
    except Exception as e:  # the app must keep working without any translator
        print("local translation failed:", e)
        en = [""] * len(lines)
    return [{"english": e, "visual": e, "tags": [], "source": "local"} for e in en]


def annotate(lines, title="", people=(), lang=None):
    """[{english, visual, tags, month, season, source}] for each lyric line (same order). `lang`: the song's
    language ("es", "en"…), None when not known."""
    if not lines:
        return []
    try:
        import anthropic
        client = anthropic.Anthropic()
        ctx = f"Song title: {title}." + (f" People in the photos: {', '.join(people)}." if people else "")
        sung = lexicon.name(lang)
        user = ctx + f"\n\nLines ({sung or 'the language they are written in'}):\n" + "\n".join(
            f"{k}. {l}" for k, l in enumerate(lines))
        kw = {}
        if MODEL.startswith(("claude-sonnet-5-5", "claude-opus-5-5")):
            # on a safety-classifier decline, the API re-runs the request on a fallback model in the same call
            kw = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        r = client.beta.messages.parse(model=MODEL, max_tokens=16000, system=SYSTEM,
                                       messages=[{"role": "user", "content": user}],
                                       output_config={"effort": "medium"}, output_format=Result, **kw)
        if r.stop_reason == "refusal" or r.parsed_output is None:
            raise RuntimeError(f"no usable answer (stop_reason={r.stop_reason})")
        by_n = {l.n: l for l in r.parsed_output.lines}
        local = None
        out = []
        for k, text in enumerate(lines):
            l = by_n.get(k)
            if l is None:  # a missing line: fill it locally
                local = local or _local(lines, lang)
                out.append(local[k])
            else:
                out.append({"english": l.english.strip(), "visual": l.visual.strip(),
                            "tags": [t.strip().lower() for t in l.tags if t.strip()][:4],
                            "month": l.month if l.month and 1 <= l.month <= 12 else None,
                            "season": l.season if l.season in ("summer", "autumn", "winter", "spring", "christmas")
                            else None, "source": MODEL})
        return out
    except Exception as e:
        print("lyrics model unavailable, using the local translator:", e)
        return _local(lines, lang)
