"""LLM step generator using Gemini.

Outputs the REAL nested schema (Goal -> Action -> StepGroup). Gemini only
writes the goal/title/description/steps/category text; deeplinks are never
written by the model. They are attached afterwards by matching each step's
own text against the real catalog (same matcher app/fallback.py uses), so a
deeplink URI can never be invented.
"""
import json

from google import genai
from google.genai import types

from .deeplinks import get_catalog

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client()  # uses GEMINI_API_KEY from environment
    return _client


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
                    "stepGroups": [
                        {"steps": ["step text derived from the SIIS content"]}
                    ],
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
- "category" is "critical" for safety/data-loss steps (like factory reset), "auto" if the step directly flips a device Settings toggle, otherwise "manual". Don't worry about getting auto/manual perfectly right - it will be corrected automatically afterwards.
- Do not include any URLs, web addresses, or email addresses anywhere in your output.
- Return ONLY JSON matching the given shape, nothing else - no deeplink fields, those are added separately.
"""


def generate(query, siis_response):
    """Returns a dict shaped like ContextDeeplinkResponse, or raises on failure
    (pipeline.py falls back to the rule-based generator if this raises)."""
    cat = get_catalog()
    content = siis_response.get("content", "")
    title = siis_response.get("title", "")

    client = _get_client()
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            f"User query: {query}\n\n"
            f"SIIS article title: {title}\n"
            f"SIIS content:\n{content}\n\n"
            f"Produce troubleshooting guidance in this shape:\n{json.dumps(_SCHEMA_HINT, indent=1)}"
        ),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    draft = json.loads(resp.text)

    # Attach real deeplinks locally by matching each step's own text - the
    # model never sees or writes a deeplink URI, so nothing can be hallucinated.
    for g in draft.get("contexts", []):
        for a in g.get("actions", []):
            for sg in a.get("stepGroups", []):
                match = cat.match(" ".join(sg.get("steps", [])))
                sg["actionableDeeplink"] = cat.actionable(match) if match else None
                sg["validationDeeplink"] = cat.validation(match) if match else None

    return draft
