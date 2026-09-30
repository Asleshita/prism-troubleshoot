# Smart Guided Troubleshooting Engine - PRISM GenAI Hackathon 3.0 (Theme 2)

Turns a raw Samsung SIIS support article and a user's query into a
structured, deeplink-enriched troubleshooting guide.

## Architecture

```
query + siis_response
        |
        v
  app/pipeline.py  --(cache hit?)--> cached response
        |  (cache miss)
        v
  app/llm_generator.py  (Gemini writes goal/title/steps/description/category
                          from the SIIS text only; never writes deeplinks)
        |  (falls back automatically if Gemini fails/unavailable)
        v
  app/fallback.py  (rule-based: extracts imperative steps directly from the
                     SIIS text - guarantees a valid, non-empty response)
        |
        v
  app/deeplinks.py  (matches each step's own text to the real 578-entry
                      deeplinks.json catalog by meaning; copies URI verbatim;
                      never invents a deeplink)
        |
        v
  app/postprocess.py  (repairs format: goal regex, 2-3 word title, "It will"
                        + 5-7 word description, score clamp, strips any URL;
                        validates every rule before returning)
        |
        v
  final ContextDeeplinkResponse JSON
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

Set your Gemini API key (get one at https://aistudio.google.com/apikey):

```bash
set GEMINI_API_KEY=your_key_here          # Windows CMD
# export GEMINI_API_KEY=your_key_here     # macOS/Linux
```

If no key is set, or the Gemini call fails for any reason, the API
automatically falls back to a rule-based generator that derives steps
directly from the SIIS text - the API never errors or returns empty.

## Run

```bash
uvicorn app.main:app --reload
```

- Health check: `GET http://localhost:8000/health` -> `{"status": "ok"}`
- API docs / try it out: `http://localhost:8000/docs`
- Main endpoint: `POST http://localhost:8000/v1/troubleshoot`

Example request body:
```json
{
  "query": "My Galaxy S22 screen is completely black and won't turn on",
  "siis_response": {
    "title": "Blank or black display on a Samsung phone or tablet",
    "content": "... SIIS article text ..."
  }
}
```

## Run with Docker

```bash
docker build -t prism-troubleshoot .
docker run -p 8000:8000 -e GEMINI_API_KEY=your_key_here prism-troubleshoot
```

## Self-check (all 20 kit scenarios)

```bash
python scripts/selfcheck.py
```
Runs every sample query through the live pipeline and checks it against
every formatting rule (goal regex, title length, description rule, score
range, auto-actions-have-deeplinks, zero URL leaks) plus the official
`schema.py`. Prints cold/warm latency per query.

## Generate the results.jsonl submission file

```bash
python scripts/generate_results.py
```
Produces `results.jsonl` at the repo root: one line per kit query, each with
8-10 diverse query_variations and the full response - the required offline
results format.

## Caching

Responses are cached by the SIIS article's content hash, so repeat calls and
paraphrases of the same underlying article are served from cache in well
under 300ms (p95). At startup, the server loads pre-computed answers from
`results.jsonl` straight into the cache (no LLM calls), so `/health` and the
20 kit scenarios are already fast the moment the server comes up. Any query
not already in `results.jsonl` is answered live on first request and cached
after that.

## Tech stack

- Python 3.11, FastAPI, Pydantic v2
- Google Gemini (`gemini-3.1-flash-lite`) for query understanding and step drafting
- In-memory cache keyed on SIIS content hash
- Rule-based fallback generator (no external dependency) as a safety net

## Known limitations

- Deeplink matching is keyword/label-based rather than embedding-based; it is
  tuned for precision (few wrong matches) over recall (a few clear matches
  may be missed and correctly left as `manual`).
- The fallback generator's phrasing is plainer than the LLM path; it exists
  purely as a safety net so the API is never non-functional.
