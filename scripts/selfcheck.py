"""Run all 20 kit scenarios through the pipeline and check every rule.
Usage (from repo root):  python scripts/selfcheck.py [--show N]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline import troubleshoot  # noqa: E402
from app.postprocess import validate  # noqa: E402

try:
    from schema import ContextDeeplinkResponse  # noqa: E402
except Exception:  # pydantic not installed
    ContextDeeplinkResponse = None

rows = json.load(open(ROOT / "data" / "siis_responses.json", encoding="utf-8"))["responses"]
show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else -1
bad = 0
print(f"{'id':8} {'cold ms':>8} {'warm ms':>8} {'acts':>4} {'auto':>4}  result")
for i, r in enumerate(rows):
    t0 = time.perf_counter(); resp = troubleshoot(r["original_query"], r["siis_response"]); cold = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter(); troubleshoot(r["original_query"], r["siis_response"]); warm = (time.perf_counter() - t0) * 1000
    errs = validate(resp)
    if ContextDeeplinkResponse is not None:
        try:
            ContextDeeplinkResponse.model_validate(resp)
        except Exception as e:  # noqa: BLE001
            errs.append(f"pydantic: {e}")
    acts = [a for g in resp["contexts"] for a in g["actions"]]
    n_auto = sum(a["category"] == "auto" for a in acts)
    bad += bool(errs)
    print(f"{r['id']:8} {cold:8.1f} {warm:8.2f} {len(acts):4} {n_auto:4}  {'OK' if not errs else 'FAIL ' + '; '.join(errs[:3])}")
    if i == show:
        print(json.dumps(resp, indent=2))
print(f"\n{len(rows) - bad}/{len(rows)} valid" + ("" if ContextDeeplinkResponse else "  (pydantic not installed - schema.py check skipped)"))
sys.exit(1 if bad else 0)
