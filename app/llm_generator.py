"""LLM step generator. Works with Claude (ANTHROPIC_API_KEY) or Gemini (GEMINI_API_KEY).

The model only writes goal/title/description/steps/category text. Deeplinks are
NEVER written by the model: they are attached afterwards by matching each step's
own text against the real catalog, so a deeplink URI can never be invented.
If no key is set or the call fails, this raises and pipeline.py uses the
rule-based fallback instead - the API never returns an error.
"""
import json
import os
import re

from .deeplinks import get_catalog

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")  # fast, single call - no racing/looping
TIMEOUT_S = 15

_SCHEMA_HINT = {
    "contexts": [
        {
            "goal": "Follow these steps to perform this <Name> Troubleshooting.",
            "title": "2-3 word title",
            "score": 0.0,
            "actions": [
                {
                    "actionName": "short name",
                    "description": "It will <5-7 words total, starting with 'It will'>",
                    "category": "auto | manual | critical",
                    "stepGroups": [{"steps": ["step text derived from the SIIS content"]}],
                }
            ],
        }
    ]
}

_SYSTEM = """You turn a raw Samsung support article into troubleshooting guidance.
Rules:
- Every step's wording MUST come from the SIIS content given to you. Do not invent steps or facts not present in that text.
- "goal" MUST match exactly: "Follow these steps to perform this <Name> Troubleshooting." or "...Configuration."
- "title" is 2-3 words.
- action "description" MUST start with "It will" and be 5-7 words total.
- "category" is "critical" for safety/data-loss steps (like factory reset), "auto" if the step directly flips a device Settings toggle, otherwise "manual". It will be corrected automatically afterwards, so don't overthink it.
- Do not include any URLs, web addresses, or email addresses anywhere in your output.
- Return ONLY JSON matching the given shape, nothing else - no deeplink fields, those are added separately.
"""


def _prompt(query, siis):
    return (
        f"User query: {query}\n\n"
        f"SIIS article title: {siis.get('title', '')}\n"
        f"SIIS content:\n{siis.get('content', '')}\n\n"
        f"Produce troubleshooting guidance in this shape:\n{json.dumps(_SCHEMA_HINT, indent=1)}"
    )


def _parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # strip code fences if present
    return json.loads(text)


def _call_claude(prompt):
    import anthropic  # lazy import so the app runs even if the package is missing

    client = anthropic.Anthropic(timeout=TIMEOUT_S)  # reads ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        temperature=0.2,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _call_gemini(prompt):
    from google import genai
    from google.genai import types

    client = genai.Client()  # library default timeout - no custom deadline, avoids the 10s-minimum trap
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM, response_mime_type="application/json", temperature=0.2),
    )
    return resp.text


def generate(query, siis_response):
    """Return a ContextDeeplinkResponse-shaped dict, or raise (pipeline falls back)."""
    prompt = _prompt(query, siis_response)
    if os.getenv("ANTHROPIC_API_KEY"):
        raw = _call_claude(prompt)
    elif os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        raw = _call_gemini(prompt)
    else:
        raise RuntimeError("No LLM key set (ANTHROPIC_API_KEY or GEMINI_API_KEY)")
    draft = _parse_json(raw)

    cat = get_catalog()
    for g in draft.get("contexts", []):
        for a in g.get("actions", []):
            for sg in a.get("stepGroups", []):
                m = cat.match(" ".join(sg.get("steps", [])))
                sg["actionableDeeplink"] = cat.actionable(m) if m else None
                sg["validationDeeplink"] = cat.validation(m) if m else None
    return draft
