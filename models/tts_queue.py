"""TTS Queue MongoDB Schema"""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


class TTSStatus(str, Enum):
    PENDING = "pending"
    PLAYING = "playing"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class TTSQueueDocument(BaseModel):
    """MongoDB document schema for TTS queue."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    session_id: str
    text: str
    status: TTSStatus = TTSStatus.PENDING
    priority: str = "normal"  # normal, high
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    interrupted_at: Optional[datetime] = None
    error_message: Optional[str] = None

    model_config = {
        "populate_by_name": True,
        "json_encoders": {datetime: lambda v: v.isoformat()},
    }


class TranscriptDocument(BaseModel):
    """MongoDB document schema for interviews.transcripts collection."""

    id: Any = Field(alias="_id")
    interview_id: str
    speaker: str  # "agent" | "candidate"
    text: str
    audio_url: Optional[str] = None
    audio_data: Optional[bytes] = None   # raw PCM bytes (pcm_22050) once played
    audio_format: Optional[str] = None  # "pcm_22050"
    timestamp: Optional[datetime] = None

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}
