"""Generate 8-10 diverse paraphrases per query without depending on any LLM
(works even with no API key / no internet). Diversity comes from combining
several independent transformations: synonym swaps, register changes
(casual/formal), reordering, and question-vs-statement framing.
"""
import random
import re

_SYNONYMS = {
    r"\bscreen\b": ["display", "screen"],
    r"\bwon'?t turn on\b": ["won't turn on", "isn't powering on", "refuses to start up", "won't boot up"],
    r"\bgoes? (completely )?blank\b": ["goes blank", "turns black", "shows nothing", "stays dark"],
    r"\bcompletely black\b": ["completely black", "totally dark", "pitch black"],
    r"\bmy\b": ["my", "the"],
    r"\bphone\b": ["phone", "device", "handset"],
    r"\btablet\b": ["tablet", "device"],
    r"\bcracked\b": ["cracked", "shattered", "broken"],
    r"\bflickers?\b": ["flickers", "flashes", "keeps flashing"],
    r"\bstops? working\b": ["stops working", "quits responding", "no longer functions"],
    r"\bdoesn'?t\b": ["doesn't", "does not", "won't"],
    r"\bI can'?t\b": ["I can't", "I cannot", "I am unable to"],
    r"\bcan'?t\b": ["can't", "cannot"],
}

_PREFIXES_CASUAL = ["Hey, ", "So ", "Ugh, ", "Quick question - ", ""]
_PREFIXES_FORMAL = ["I am writing regarding an issue: ", "I would like to report that ", "Please advise: ", ""]
_SUFFIXES = ["", " Any idea what's wrong?", " Please help.", " What should I do?", " Can this be fixed?"]


def _apply_synonyms(text, rng):
    out = text
    for pattern, options in _SYNONYMS.items():
        if re.search(pattern, out, re.I):
            repl = rng.choice(options)
            out = re.sub(pattern, repl, out, count=1, flags=re.I)
    return out


def _to_question(text):
    t = text.rstrip(".!? ")
    t = re.sub(r"^(My|The)\b", "Why is my", t, count=1) if not t.lower().startswith("why") else t
    return t + "?"


def _shorten(text, rng):
    """Keep only the core clause(s), dropping trailing detail, for a punchier variant."""
    parts = re.split(r",\s*(?:so|and|which|while)\b", text, maxsplit=1, flags=re.I)
    return parts[0].strip().rstrip(".") + "."


def _reorder(text):
    """Move a trailing 'so ...' / 'and ...' clause to the front when present."""
    m = re.match(r"^(.*?),\s*(so|and)\s+(.*)$", text, re.I)
    if not m:
        return text
    head, _, tail = m.groups()
    return tail[0].upper() + tail[1:].rstrip(".") + ", " + head[0].lower() + head[1:] + "."


def generate_variations(query, n_min=8, n_max=10, seed=None):
    """Return n_min..n_max unique paraphrases of query (never includes the original verbatim)."""
    base = re.sub(r"^\d+\.\s*", "", query.strip().strip('"'))  # drop leading "1. " numbering
    rng = random.Random(seed if seed is not None else hash(base) & 0xFFFFFFFF)
    variants = set()
    attempts = 0
    target = rng.randint(n_min, n_max)
    transforms = [
        lambda t: rng.choice(_PREFIXES_CASUAL) + t[0].lower() + t[1:] if rng.choice(_PREFIXES_CASUAL) else t,
        lambda t: rng.choice(_PREFIXES_FORMAL) + (t[0].lower() + t[1:] if rng.choice(_PREFIXES_FORMAL) else t[0].upper() + t[1:]),
        lambda t: t.rstrip(".") + rng.choice(_SUFFIXES),
        _to_question,
        lambda t: _shorten(t, rng),
        _reorder,
        lambda t: t,  # identity, so synonym-only swaps also get a chance
    ]
    while len(variants) < target and attempts < target * 15:
        attempts += 1
        t = _apply_synonyms(base, rng)
        t = rng.choice(transforms)(t)
        t = re.sub(r"\s+", " ", t).strip()
        t = re.sub(r"([.?!])\1+$", r"\1", t)
        if t and t.lower() != base.lower() and t not in variants:
            variants.add(t)
    return list(variants)[:n_max] or [base + " (please help)"]
