"""Request pipeline: cache -> (optional LLM) -> repair -> validate -> fallback.

DHRUTHI: plug your LLM in by setting LLM_GENERATOR to a function
    (query: str, siis_response: dict) -> dict   # a ContextDeeplinkResponse-shaped dict
Whatever it returns is passed through repair()/validate(); if it fails or is
invalid, the rule-based fallback is used, so the API never returns an error.
"""
import hashlib

from .fallback import fallback_response
from .postprocess import repair, validate

try:
    from .llm_generator import generate as LLM_GENERATOR
except Exception:
    LLM_GENERATOR = None  # e.g. GEMINI_API_KEY not set, or google-genai not installed

_cache = {}


def _siis_key(siis):
    raw = (siis.get("title", "") + "\n" + siis.get("content", "")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def troubleshoot(query, siis):
    # Cache on the SIIS article: every paraphrase of a query that arrives with the
    # same article is served instantly. (Trade-off: two different queries that share
    # one article get the same answer - acceptable since steps must come from the article.)
    key = _siis_key(siis or {})
    hit = _cache.get(key)
    if hit is not None:
        return hit
    resp = None
    if LLM_GENERATOR is not None:
        try:
            resp = repair(LLM_GENERATOR(query, siis))
            if validate(resp):
                resp = None
        except Exception:
            resp = None
    if resp is None:
        resp = repair(fallback_response(query, siis))
    _cache[key] = resp
    return resp


def warm_cache(items):
    """items: iterable of (query, siis_response). Call at startup so first hits are fast."""
    for q, s in items:
        troubleshoot(q, s)
