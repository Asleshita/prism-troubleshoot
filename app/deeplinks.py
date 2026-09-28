"""Deeplink catalog matcher. Pure Python (no extra dependencies).

Matches a step's text to the catalog by *meaning* (validation key / description),
never by URI. URIs are always copied verbatim from the catalog.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DUMMY_URI = "bixby://dummy_positive"

_STOP = {
    "a", "an", "the", "of", "to", "and", "or", "in", "on", "off", "for", "with", "via",
    "your", "you", "it", "is", "are", "be", "this", "that", "as", "at", "by", "from",
    "opens", "open", "page", "device", "settings", "setting", "when", "while", "use",
    "using", "up", "turn", "only", "all", "then", "tap", "select",
    "icon", "option", "menu", "switch", "switche", "field", "toggle", "tab", "setting",
}
# TV / appliance entries are not relevant to phone or tablet troubleshooting.
_IRRELEVANT = re.compile(r"TV Settings|TV Bixby|refrigerator|air conditioner", re.I)
_UI_VERB = r"(?:tap|select|open|choose|touch|go to|navigate to|turn on|turn off)"
_TYPE_PREF = {
    "on": ["onURL", "onClickURL", "updateURL", "offURL"],
    "off": ["offURL", "onClickURL", "updateURL", "onURL"],
    None: ["onClickURL", "onURL", "updateURL", "offURL"],
}


def _stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def tokens(text):
    t = (text or "").lower().replace("back up", "backup")
    return [w for w in (_stem(x) for x in re.findall(r"[a-z0-9]+", t)) if w not in _STOP and len(w) > 1]


def _desc_core(desc):
    d = re.sub(r"^(Opens|Enables|Disables|Updates)( the)? ", "", desc or "")
    d = re.sub(r"\s+(?:settings page\s+|settings\s+)?(?:in|via)\s+(?:device Settings|Samsung [\w ]+?|TV \w+)\s+on the device\.?$", "", d)
    d = re.sub(r"\s+to a specified value", "", d)
    return d


_VERB_RE = re.compile(
    r"\b(?:tap|select|open|choose|touch and hold|touch|go to|navigate to(?: and open)?|turn on|turn off|enable|disable)\b\s*(?:on\s+)?", re.I)
_CUT = re.compile(r",|\.|;|\band then\b|\bwhen\b|\bif\b|\buntil\b|\bso that\b|\bby\b|\bfrom\b")


def _clauses(text):
    """Text fragments that directly follow a UI verb, e.g. 'tap Display, and then tap Wi-Fi' -> ['Display', 'Wi-Fi']."""
    out = []
    for m in _VERB_RE.finditer(text or ""):
        rest = _CUT.split((text or "")[m.end():m.end() + 70])[0].strip()
        if rest:
            out.append(rest)
    return out


class Catalog:
    def __init__(self, path=None):
        raw = json.load(open(path or DATA_DIR / "deeplinks.json", encoding="utf-8"))["deeplinks"]
        self.by_uri = {e["deeplink"]: e for e in raw}
        self.valid_uris = set(self.by_uri)
        for e in raw:
            if e.get("validation") and e["validation"].get("deeplink"):
                self.valid_uris.add(e["validation"]["deeplink"])
        self.entries = [e for e in raw if e["deeplink"] != DUMMY_URI and not _IRRELEVANT.search(e["description"])]
        self._phrases = []
        df = Counter()
        for e in self.entries:
            key = (e.get("validation") or {}).get("key") or e.get("message") or ""
            key_np = re.sub(r"\([^)]*\)", "", key)
            phrases = []
            for ph in (tokens(key_np), tokens(key), tokens(_desc_core(e["description"]))):
                ph = list(dict.fromkeys(ph))
                if ph and ph not in phrases:
                    phrases.append(ph)
            self._phrases.append(phrases)
            df.update({t for p in phrases for t in p})
        n = len(self.entries)
        self._idf = lambda t: math.log((n + 1) / (df.get(t, 0) + 1)) + 1

    # ---- matching -------------------------------------------------------
    def match(self, text, min_cov=0.75):
        """Best catalog entry for a step, or None. Precision-first:
        the label must appear in the clause right after a UI verb (tap/select/go to...),
        and single-word labels must match the clause exactly (and be capitalised)."""
        low = (text or "").lower()
        if re.search(r"\b(turn on|turn it on|enable|enabling|switch on|toggle on)\b", low):
            hint = "on"
        elif re.search(r"\b(turn off|disable|disabling|switch off|toggle off)\b", low):
            hint = "off"
        else:
            hint = None
        pref = _TYPE_PREF[hint]
        best, best_rank = None, None
        for clause in _clauses(text):
            q = set(tokens(clause))
            if not q:
                continue
            caps = {_stem(w.lower()) for w in re.findall(r"[A-Za-z0-9]+", clause) if w[0].isupper()}
            for e, phrases in zip(self.entries, self._phrases):
                cov_best, spec_best = 0.0, 0.0
                for ph in phrases:
                    tot = sum(self._idf(t) for t in ph)
                    if len(ph) == 1:
                        if q != {ph[0]} or ph[0] not in caps:
                            continue
                        cov = 1.0
                    else:
                        hit = [t for t in ph if t in q]
                        if len(hit) < 2 or (len(ph) <= 3 and len(hit) < len(ph)):
                            continue
                        cov = sum(self._idf(t) for t in hit) / tot
                    if cov > cov_best:
                        cov_best, spec_best = cov, tot
                if cov_best < min_cov:
                    continue
                t = e.get("originalType")
                rank = (round(cov_best, 2), spec_best, -pref.index(t) if t in pref else -9)
                if best_rank is None or rank > best_rank:
                    best, best_rank = e, rank
        return best

    # ---- output shaping -------------------------------------------------
    @staticmethod
    def actionable(e):
        return {"deeplink": e["deeplink"], "description": e["description"],
                "message": e.get("message") or "", "originalType": e.get("originalType")}

    @staticmethod
    def validation(e):
        v = e.get("validation")
        if not v:
            return None
        return {k: v[k] for k in ("deeplink", "key", "resultType", "condition", "value") if v.get(k) is not None}


_catalog = None


def get_catalog():
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog


def dummy_deeplink(screen):
    """Generic placeholder for a Settings screen with no catalog entry (5-7 word description)."""
    screen = " ".join(screen.split()[:2]) or "main"
    return {"deeplink": DUMMY_URI, "description": f"Opens the {screen} Settings screen",
            "message": f"Open {screen} Settings", "originalType": "placeholder"}
