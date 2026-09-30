import json
import threading
from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel

from .deeplinks import DATA_DIR
from .pipeline import load_cached_results, troubleshoot, warm_cache

app = FastAPI(title="Smart Guided Troubleshooting Engine")
ROOT = DATA_DIR.parent


class TroubleshootRequest(BaseModel):
    query: str
    siis_response: Dict[str, Any]


def _warm_in_background():
    try:
        rows = json.load(open(DATA_DIR / "siis_responses.json", encoding="utf-8"))["responses"]
        warm_cache((r["original_query"], r["siis_response"]) for r in rows)
    except Exception:
        pass  # warming is an optimisation only


@app.on_event("startup")
def _warm():
    # Fast path: load saved answers from results.jsonl (no LLM calls, instant startup).
    # If that file is missing, warm in a background thread so /health is never blocked.
    if load_cached_results(ROOT / "results.jsonl", DATA_DIR / "siis_responses.json") == 0:
        threading.Thread(target=_warm_in_background, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/troubleshoot")
def v1_troubleshoot(req: TroubleshootRequest):
    return troubleshoot(req.query, req.siis_response)
