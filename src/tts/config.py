"""TTS Service Configuration"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable configuration loaded from environment variables."""

    # MongoDB
    mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_db: str = os.getenv("MONGODB_DB", "tts_service")
    tts_queue_collection: str = "tts_queue"

    # NATS
    nats_uri: str = os.getenv("NATS_URI", "nats://localhost:4222")
    nats_interrupt_subject: str = "tts.interrupt"
    nats_max_reconnect_attempts: int = 5

    # PulseAudio
    pulse_server: str = os.getenv("PULSE_SERVER", "unix:/run/user/1000/pulse/native")
    virtual_mic: str = os.getenv("VIRTUAL_MIC", "virtual_mic")

    # Piper TTS
    piper_model_path: str = os.getenv(
        "PIPER_MODEL_PATH",
        "/app/models/piper/en_US-amy-medium.onnx",
    )
    piper_command: str = "piper"

    # Audio
    sample_rate: int = 22050
    channels: int = 1
    dtype: str = "int16"
    chunk_size: int = 4096  # bytes

    # Timeouts
    first_chunk_timeout: float = 10.0  # seconds (model load time)
    next_chunk_timeout: float = 0.5    # seconds (end-of-utterance)

    # Performance
    interruption_latency_ms: int = 50

    # Reconnection
    mongo_max_retries: int = 5
    mongo_retry_base_delay: float = 1.0  # seconds


config = Config()
