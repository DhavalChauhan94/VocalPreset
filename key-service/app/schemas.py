"""Response models. Field names and order match the API contract in README.md."""
from pydantic import BaseModel


class KeyResult(BaseModel):
    key: str
    scale: str
    key_string: str
    display_key: str
    confidence: float
    agreement: str
    scale_notes: list[str]
    pitch_classes: list[int]
    relative_key: str
    low_confidence: bool
    warnings: list[str]
    analysis_seconds: float


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
