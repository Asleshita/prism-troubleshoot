import json
from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel

from .deeplinks import DATA_DIR
from .pipeline import troubleshoot, warm_cache

app = FastAPI(title="Smart Guided Troubleshooting Engine")


class TroubleshootRequest(BaseModel):
    query: str
    siis_response: Dict[str, Any]


@app.on_event("startup")
def _warm():
    try:
        rows = json.load(open(DATA_DIR / "siis_responses.json", encoding="utf-8"))["responses"]
        warm_cache((r["original_query"], r["siis_response"]) for r in rows)
    except Exception:
        pass  # warming is an optimisation only


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/troubleshoot")
def v1_troubleshoot(req: TroubleshootRequest):
    return troubleshoot(req.query, req.siis_response)
