from pydantic import BaseModel, Field
from typing import List, Optional

class TroubleshootStep(BaseModel):
    title: str = Field(description="2-3 words title")
    description: str = Field(description="5-7 words starting with 'It will'")

class TroubleshootResponse(BaseModel):
    goal: str = Field(description="Goal format statement")
    score: float = Field(description="Confidence or relevance score between 0 and 1")
    steps: List[TroubleshootStep]