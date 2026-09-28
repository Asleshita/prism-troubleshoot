"""Safety net applied to EVERY response (LLM or fallback) before it is returned.

repair()   -> forces the format rules (goal regex, title 2-3 words, description
              "It will" + 5-7 words, score 0-1, no URLs, real catalog deeplinks).
validate() -> returns a list of rule violations (empty list == all good).
"""
import json
import re

from .deeplinks import DUMMY_URI, Catalog, dummy_deeplink, get_catalog

GOAL_RE = re.compile(r"^Follow these steps to perform this .+ (Troubleshooting|Configuration)\.$")
LEAK_RE = re.compile(r"(https?|ftp)://|www\.|\.com|\.html?|\.org|\.net|!\[|\]\(|<a |</a>|<img|@", re.I)
CATEGORIES = {"auto", "manual", "critical"}

_URL_PATTERNS = [
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),                      # markdown images
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),                   # markdown links -> text
    (re.compile(r"<[^>]+>"), ""),                                    # html/link tags
    (re.compile(r"(https?|ftp)://\S+", re.I), ""),                   # urls
    (re.compile(r"\bwww\.\S+", re.I), ""),
    (re.compile(r"\S+@\S+"), ""),                                    # emails
    (re.compile(r"\b[\w-]+(\.[\w-]+)*\.(com|net|org|html?|co|in|io)\b", re.I), ""),  # bare domains
]


def scrub(text):
    """Remove anything URL-like from free text."""
    t = str(text or "")
    for pat, rep in _URL_PATTERNS:
        t = pat.sub(rep, t)
    t = LEAK_RE.sub("", t)  # last-resort safety net
    return re.sub(r"\s+", " ", t).strip()


def _words(s):
    return s.split()


def fix_title(title, fallback="Device Troubleshooting"):
    w = re.findall(r"[A-Za-z0-9+/'-]+", scrub(title)) or re.findall(r"[A-Za-z0-9+/'-]+", fallback)
    w = w[:3]
    if len(w) < 2:
        w.append("Troubleshooting")
    return " ".join(w)


def fix_goal(goal, title):
    g = scrub(goal)
    if GOAL_RE.match(g):
        return g
    kind = "Configuration" if re.search(r"configuration", g, re.I) else "Troubleshooting"
    base = re.sub(r"(?i)^follow these steps to perform this\s*", "", g)
    base = re.sub(r"(?i)\s*(troubleshooting|configuration)?\s*\.?\s*$", "", base).strip()
    if not base:
        base = re.sub(r"(?i)\s*(troubleshooting|configuration)\s*$", "", title).strip() or "Device"
    return f"Follow these steps to perform this {base} {kind}."


def fix_description(desc, name="this task"):
    w = _words(scrub(desc).rstrip(".!"))
    if [x.lower() for x in w[:2]] != ["it", "will"]:
        w = ["It", "will"] + ([x.lower() if i else x for i, x in enumerate(w)] if w else [])
    w = w[:7]
    filler = ["help", "you", "with", "this", "task"]
    i = 0
    while len(w) < 5:
        w.append(filler[i % len(filler)])
        i += 1
    return " ".join(w)


def _fix_action_deeplink(a, cat):
    """Replace any model-provided deeplink with the canonical catalog entry."""
    if not a or not a.get("deeplink"):
        return None, None
    uri = a["deeplink"]
    if uri not in cat.by_uri:
        return None, None  # hallucinated URI -> drop
    e = cat.by_uri[uri]
    if uri == DUMMY_URI:
        d = {"deeplink": DUMMY_URI,
             "description": fix_description_screen(a.get("description")),
             "message": scrub(a.get("message")) or "Open the relevant Settings screen",
             "originalType": "placeholder"}
        return d, None
    return cat.actionable(e), cat.validation(e)


def fix_description_screen(desc):
    """Dummy-deeplink descriptions must also be 5-7 words."""
    w = _words(scrub(desc))
    if len(w) > 7:
        w = w[:7]
    filler = ["Opens", "the", "relevant", "Settings", "screen"]
    while len(w) < 5:
        w.append(filler[len(w) % len(filler)])
    return " ".join(w)


def repair(resp, cat=None):
    """Return a cleaned copy of resp (dict). Never raises on malformed input."""
    cat = cat or get_catalog()
    contexts_out = []
    for g in (resp or {}).get("contexts") or []:
        actions_out = []
        for a in g.get("actions") or []:
            groups_out = []
            for sg in a.get("stepGroups") or []:
                steps = [s for s in (scrub(x) for x in sg.get("steps") or []) if s]
                if not steps:
                    continue
                act, val = _fix_action_deeplink(sg.get("actionableDeeplink"), cat)
                if act is None:
                    val = None
                groups_out.append({"steps": steps, "actionableDeeplink": act, "validationDeeplink": val})
            if not groups_out:
                continue
            name = scrub(a.get("actionName")) or "Follow the steps"
            category = a.get("category") if a.get("category") in CATEGORIES else "manual"
            if category == "auto" and not any(x["actionableDeeplink"] for x in groups_out):
                category = "manual"  # auto without a deeplink loses points
            actions_out.append({"actionName": name, "description": fix_description(a.get("description"), name),
                                "stepGroups": groups_out, "category": category})
        if not actions_out:
            continue
        title = fix_title(g.get("title"))
        try:
            score = float(g.get("score", 0.8))
        except (TypeError, ValueError):
            score = 0.8
        contexts_out.append({"goal": fix_goal(g.get("goal"), title), "title": title,
                             "score": min(1.0, max(0.0, score)), "actions": actions_out})
    return {"contexts": contexts_out}


def validate(resp, cat=None):
    """List every rule violation in resp (empty list == valid)."""
    cat = cat or get_catalog()
    errs = []
    ctxs = (resp or {}).get("contexts") or []
    if not ctxs:
        errs.append("contexts is empty")
    for gi, g in enumerate(ctxs):
        p = f"contexts[{gi}]"
        if not GOAL_RE.match(g.get("goal", "")):
            errs.append(f"{p}.goal does not match regex: {g.get('goal')!r}")
        n = len(_words(g.get("title", "")))
        if not 2 <= n <= 3:
            errs.append(f"{p}.title has {n} words")
        if not 0.0 <= g.get("score", -1) <= 1.0:
            errs.append(f"{p}.score out of range")
        if not g.get("actions"):
            errs.append(f"{p}.actions empty")
        for ai, a in enumerate(g.get("actions") or []):
            q = f"{p}.actions[{ai}]"
            d = a.get("description", "")
            if not d.startswith("It will") or not 5 <= len(_words(d)) <= 7:
                errs.append(f"{q}.description bad: {d!r}")
            if a.get("category") not in CATEGORIES:
                errs.append(f"{q}.category invalid")
            groups = a.get("stepGroups") or []
            if not groups:
                errs.append(f"{q}.stepGroups empty")
            if a.get("category") == "auto" and not any(x.get("actionableDeeplink") for x in groups):
                errs.append(f"{q} is auto but has no actionableDeeplink")
            for si, sg in enumerate(groups):
                if not sg.get("steps"):
                    errs.append(f"{q}.stepGroups[{si}].steps empty")
                for key in ("actionableDeeplink", "validationDeeplink"):
                    dl = sg.get(key)
                    if dl and dl.get("deeplink") not in cat.valid_uris:
                        errs.append(f"{q}.stepGroups[{si}].{key} not in catalog: {dl.get('deeplink')}")
                dl = sg.get("actionableDeeplink")
                if dl and dl.get("deeplink") == DUMMY_URI and not 5 <= len(_words(dl.get("description", ""))) <= 7:
                    errs.append(f"{q}.stepGroups[{si}] dummy description must be 5-7 words")
    if LEAK_RE.search(json.dumps(resp or {})):
        errs.append("URL-like text found in response (G5 gate)")
    return errs
