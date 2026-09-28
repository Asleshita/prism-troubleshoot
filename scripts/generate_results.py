"""Build the required results.jsonl submission file:
one line per kit query, each with 8-10 query_variations and the full response.

Usage (from repo root, with venv active):
    python scripts/generate_results.py
Output: results.jsonl in the repo root.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline import troubleshoot  # noqa: E402
from app.variations import generate_variations  # noqa: E402

rows = json.load(open(ROOT / "data" / "siis_responses.json", encoding="utf-8"))["responses"]
out_path = ROOT / "results.jsonl"

with open(out_path, "w", encoding="utf-8") as f:
    for r in rows:
        query = r["original_query"]
        siis = r["siis_response"]
        variations = generate_variations(query, seed=r["id"])
        response = troubleshoot(query, siis)
        line = {"query": query, "query_variations": variations, "response": response}
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
        n = len(variations)
        flag = "" if 8 <= n <= 10 else "  <-- WRONG COUNT, check app/variations.py"
        print(f"{r['id']:8} {n} variations{flag}")

print(f"\nWrote {len(rows)} lines to {out_path}")
