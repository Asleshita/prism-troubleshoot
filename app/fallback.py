"""Rule-based response builder that works WITHOUT an LLM.

Used (a) as the safety net when the LLM fails/times out and (b) as the baseline
for unseen scenarios. Every step is copied from the SIIS text (nothing invented).
"""
import re

from .deeplinks import dummy_deeplink, get_catalog, tokens
from .postprocess import scrub

_VERBS = (
    "navigate|go|tap|touch|press|swipe|select|open|connect|turn|check|restart|charge|contact|visit|try|"
    "insert|remove|ensure|make sure|clear|enable|disable|perform|use|place|plug|shine|examine|inspect|"
    "increase|adjust|update|review|enter|locate|confirm|schedule|back up|scan|drag|disconnect|force|"
    "power|reset|uninstall|switch|change|test|wait|keep|avoid|provide|send|schedule|look"
)
_IMPERATIVE = re.compile(
    r"^(?:(?:first|next|then|now|also|finally|alternatively|afterward|after that)[,]?\s+)?"
    r"(?:(?:please|let's)\s+)?(?:carefully\s+|gently\s+|simply\s+)?(?:" + _VERBS + r")\b", re.I)
_HEADING = re.compile(r"^\s*#{1,6}\s*(.*\S)\s*$")
_STOP_TITLE = {"a", "an", "the", "on", "your", "to", "or", "of", "and", "in", "for", "with", "samsung",
               "galaxy", "phone", "tablet", "when", "using", "is", "not", "does", "doesn't", "use"}
_CRITICAL = re.compile(r"factory data reset|erase all|liquid|delete all", re.I)


def _clean_heading(h):
    h = re.sub(r"^(step\s*\d+\s*[:.\-]\s*|\d+\s*[.)]\s*)", "", h.strip(), flags=re.I)
    return scrub(h).strip(" :.-*")


def _split_sections(content, title):
    content = re.sub(r"^[^\n]*?\)\s*:\s*", "", content or "", count=1)  # drop "Category,... Title (...):" prefix
    g = re.search(r"\n\s*#*\s*Glossary\s*\n", content)
    if g:
        content = content[:g.start()]  # definitions are not steps
    sections, name, lines = [], title, []
    for line in content.split("\n"):
        m = _HEADING.match(line)
        if m:
            if lines:
                sections.append((name, lines))
            name, lines = _clean_heading(m.group(1)) or title, []
        elif line.strip():
            lines.append(line.strip())
    if lines:
        sections.append((name, lines))
    return sections


def _sentences(lines):
    out = []
    for line in lines:
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", line):
            s = scrub(s.replace("**", "")).strip()
            if 5 <= len(s) <= 260 and max(len(w) for w in s.split()) <= 28:  # skip garbled text
                out.append(s)
    return out


_INSTRUCTION = re.compile(r"\b(go to|navigate to|tap|touch and hold|press and hold|swipe|select)\b", re.I)


def _steps_for(lines):
    """Keep instruction-like sentences: imperatives, or any sentence that tells the user where to tap/go."""
    steps = [s for s in _sentences(lines)
             if _IMPERATIVE.match(s) or (re.match(r"^(To|Once|After|Before)\b", s) and _INSTRUCTION.search(s))]
    return steps[:7]


_NAV = re.compile(r"\b(?:go to|navigate to(?: and open)?|open)\s+Settings\b", re.I)


def _screen_name(text):
    """First screen tapped after entering Settings, e.g. 'Navigate to Settings. Tap Apps.' -> 'Apps'."""
    m = re.search(r"\bSettings\b.*?(?i:\btap)\s+(?:the\s+|on\s+)?([A-Z][\w+-]*(?:\s+[A-Z][\w+-]*)?)", text)
    return m.group(1) if m else "main"


def _group_steps(steps):
    """Consecutive steps are grouped so a matched step keeps its navigation steps."""
    cat, groups, buf = get_catalog(), [], []
    for s in steps:
        buf.append(s)
        e = cat.match(s)
        if e:
            groups.append({"steps": buf, "actionableDeeplink": cat.actionable(e), "validationDeeplink": cat.validation(e)})
            buf = []
    if buf:
        text = " ".join(buf)
        if _NAV.search(text) and re.search(r"\btap\b", text, re.I):
            groups.append({"steps": buf, "actionableDeeplink": dummy_deeplink(_screen_name(text)), "validationDeeplink": None})
        else:
            groups.append({"steps": buf, "actionableDeeplink": None, "validationDeeplink": None})
    return groups


def _title(siis_title):
    w = [x for x in re.findall(r"[A-Za-z0-9+/'-]+", siis_title or "") if x.lower() not in _STOP_TITLE]
    return " ".join(w[:3]) if len(w) >= 2 else "Device Troubleshooting"


def _description(name):
    w = [x.lower() for x in re.findall(r"[A-Za-z0-9+/'-]+", name) if x.lower() not in _STOP_TITLE][:3]
    return "It will help you " + " ".join(w or ["fix this"])


def fallback_response(query, siis):
    title_raw = scrub((siis or {}).get("title", "")) or "Device issue"
    sections = _split_sections((siis or {}).get("content", ""), title_raw)
    qtok = set(tokens(query))
    scored = []
    for i, (name, lines) in enumerate(sections):
        if re.search(r"glossary", name, re.I):
            continue
        steps = _steps_for(lines)
        if not steps:
            continue
        overlap = len(qtok & set(tokens(name + " " + " ".join(lines))))
        scored.append((i, overlap, name, steps))
    # keep the 4 most query-relevant sections, in their original order
    keep = sorted(sorted(scored, key=lambda x: (-x[1], x[0]))[:4], key=lambda x: x[0])
    actions = []
    for _, _, name, steps in keep:
        groups = _group_steps(steps)
        auto = any(g["actionableDeeplink"] for g in groups)
        crit = any(_CRITICAL.search(s) for s in steps)
        actions.append({"actionName": " ".join(name.split()[:8]), "description": _description(name),
                        "stepGroups": groups, "category": "auto" if auto else ("critical" if crit else "manual")})
    if not actions:  # unseen/odd content: still return something derived from the text
        sents = _sentences(re.sub(r"^[^\n]*?\)\s*:\s*", "", (siis or {}).get("content", ""), count=1).split("\n"))[:3]
        sents = sents or [title_raw]
        actions = [{"actionName": " ".join(title_raw.split()[:8]), "description": _description(title_raw),
                    "stepGroups": [{"steps": sents, "actionableDeeplink": None, "validationDeeplink": None}],
                    "category": "manual"}]
    title = _title(title_raw)
    return {"contexts": [{"goal": f"Follow these steps to perform this {title} Troubleshooting.",
                          "title": title, "score": 0.85 if any(a["category"] == "auto" for a in actions) else 0.75,
                          "actions": actions}]}
