from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    id: int | None = None
    case_id: str
    segment_text: str
    timestamp: str
    segment_type: str  # "partial" or "committed"
    created_at: str | None = None


class TranscriptResponse(BaseModel):
    segments: list[TranscriptSegment]
    total: int
