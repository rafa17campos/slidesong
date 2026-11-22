"""Lyrics translation to English, fully local (CTranslate2 int8 models in data/models, converted once from the
official Helsinki-NLP / Meta checkpoints). English matches photos better with the multilingual CLIP model and is
the language of the RAM++ tags."""
import os
import threading
from pathlib import Path
from . import config, lexicon

DATA = config.DATA
MODELS = {
    "nllb": DATA / "models" / "nllb-600m-ct2",           # facebook/nllb-200-distilled-600M
    "opus": DATA / "models" / "opus-mt-es-en-ct2",        # Helsinki-NLP/opus-mt-es-en
}
DEFAULT = config.env("TRANSLATOR", "nllb")

_lock = threading.Lock()
_loaded = {}


def _load(name):
    import ctranslate2
    import sentencepiece as spm
    with _lock:
        if name not in _loaded:
            path = MODELS[name]
            tr = ctranslate2.Translator(str(path), device="cpu", compute_type="int8", inter_threads=1)
            if name == "nllb":
                sp = spm.SentencePieceProcessor(model_file=str(path / "sentencepiece.bpe.model"))
                _loaded[name] = (tr, sp, sp)
            else:
                _loaded[name] = (tr, spm.SentencePieceProcessor(model_file=str(path / "source.spm")),
                                 spm.SentencePieceProcessor(model_file=str(path / "target.spm")))
        return _loaded[name]


def _model_for(lang):
    """The Spanish-only model is used for Spanish only; NLLB for every other language."""
    return DEFAULT if (lang or "es") == "es" else "nllb"


def available(name=None, lang=None):
    return (MODELS[name or _model_for(lang)] / "model.bin").exists()


def to_english(lines, lang=None, name=None):
    """Translate lyric lines in `lang` ("es", "fr"…; None = Spanish) to English; empty lines stay empty."""
    name = name or _model_for(lang)
    if not lines:
        return []
    tr, sp_src, sp_tgt = _load(name)
    idx = [k for k, l in enumerate(lines) if l.strip()]
    src = [sp_src.encode(lines[k].strip(), out_type=str) for k in idx]
    if name == "nllb":
        src = [[lexicon.nllb(lang)] + s + ["</s>"] for s in src]
        res = tr.translate_batch(src, target_prefix=[["eng_Latn"]] * len(src), beam_size=4, max_decoding_length=128)
        outs = [sp_tgt.decode([t for t in r.hypotheses[0] if t != "eng_Latn"]) for r in res]
    else:
        src = [s + ["</s>"] for s in src]
        res = tr.translate_batch(src, beam_size=4, max_decoding_length=128)
        outs = [sp_tgt.decode(r.hypotheses[0]) for r in res]
    out = [""] * len(lines)
    for k, o in zip(idx, outs):
        out[k] = o.strip()
    return out
