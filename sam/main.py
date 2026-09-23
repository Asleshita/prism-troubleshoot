import os
import re
from fastapi import FastAPI, HTTPException, status
from google import genai
from google.genai import types

from schema import TroubleshootResponse, TroubleshootStep

app = FastAPI(title="Troubleshooter API", version="1.0.0")

# Initialize Gemini Client (uses GEMINI_API_KEY from environment)
client = genai.Client()


def sanitize_text(text: str) -> str:
    """Removes URLs and strips extra whitespace."""
    # Regex to match http, https, and www URLs
    url_pattern = r'https?://\S+|www\.\S+'
    text_no_urls = re.sub(url_pattern, '', text)
    return ' '.join(text_no_urls.split())


def fix_and_validate_format(data: TroubleshootResponse) -> TroubleshootResponse:
    """
    Validation & Repair Checker enforcing formatting constraints:
    1. Removes all URLs from text fields.
    2. Ensures titles are trimmed to 2-3 words.
    3. Ensures descriptions are 5-7 words starting with 'It will'.
    4. Clamps score strictly between 0.0 and 1.0.
    """
    # Fix Goal
    clean_goal = sanitize_text(data.goal)
    
    # Fix Score
    clean_score = max(0.0, min(1.0, float(data.score)))
    
    # Fix Steps
    clean_steps = []
    for step in data.steps:
        # Sanitize Title & strip URLs
        title_text = sanitize_text(step.title)
        title_words = title_text.split()
        if len(title_words) < 2:
            title_words.append("step")
        elif len(title_words) > 3:
            title_words = title_words[:3]
        fixed_title = " ".join(title_words).capitalize()

        # Sanitize Description & strip URLs
        desc_text = sanitize_text(step.description)
        desc_words = desc_text.split()

        # Enforce "It will" prefix
        if len(desc_words) < 2 or desc_words[0].lower() != "it" or desc_words[1].lower() != "will":
            # Strip existing "it" or "will" if partial to avoid duplication
            filtered = [w for w in desc_words if w.lower() not in ("it", "will")]
            desc_words = ["It", "will"] + filtered

        # Enforce 5-7 words length
        if len(desc_words) < 5:
            # Pad with context filler words to reach minimum length of 5
            padding = ["resolve", "the", "underlying", "issue", "now"]
            desc_words.extend(padding[: 5 - len(desc_words)])
        elif len(desc_words) > 7:
            desc_words = desc_words[:7]

        fixed_desc = " ".join(desc_words)

        clean_steps.append(
            TroubleshootStep(title=fixed_title, description=fixed_desc)
        )

    return TroubleshootResponse(
        goal=clean_goal,
        score=clean_score,
        steps=clean_steps
    )


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """Health endpoint returning operational status."""
    return {"status": "ok"}


@app.post("/v1/troubleshoot", response_model=TroubleshootResponse)
def troubleshoot(issue_description: str):
    """
    Accepts an issue description, generates structured troubleshooting steps via Gemini,
    applies format correction rules, and returns the verified JSON payload.
    """
    if not issue_description.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="issue_description cannot be empty."
        )

    system_instruction = (
        "You are an expert technical troubleshooter. Generate a structured JSON response matching the requested schema.\n"
        "STRICT CONSTRAINTS:\n"
        "1. Do NOT include any URLs anywhere in the response.\n"
        "2. Each step title MUST be exactly 2 or 3 words long.\n"
        "3. Each step description MUST be 5 to 7 words long and MUST start with the words 'It will'.\n"
        "4. Score must be a floating point value between 0.0 and 1.0."
    )

    try:
        # Request Structured Output from Gemini
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Troubleshoot the following issue: {issue_description}",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=TroubleshootResponse,
                temperature=0.2,
            )
        )

        # Parse into Pydantic model
        raw_output = TroubleshootResponse.model_validate_json(response.text)

        # Run through the format checker & repair function
        validated_output = fix_and_validate_format(raw_output)

        return validated_output

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Troubleshooting pipeline failed: {str(e)}"
        )