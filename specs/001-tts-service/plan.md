# Implementation Plan: TTS Service

**Branch**: `001-tts-service` | **Date**: 2026-02-20 | **Spec**: [spec.md](spec.md)

## Summary

Build a standalone TTS service that listens to MongoDB `tts_queue` for text-to-speech tasks, synthesizes speech using Piper TTS, plays audio via sounddevice to PulseAudio virtual microphone, and supports sub-50ms interruption via NATS Pub/Sub.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: pymongo (MongoDB), nats-py (NATS), sounddevice (audio), piper-tts (TTS engine)
**Storage**: MongoDB (tts_queue collection)
**Testing**: pytest with asyncio support
**Target Platform**: Docker containers (Linux, PulseAudio)
**Project Type**: Single service (standalone TTS microservice)
**Performance Goals**: First audio 100-200ms, interruption <50ms
**Constraints**: Single utterance at a time, interruptible playback
**Scale/Scope**: 1 service, ~500-1000 LOC, real-time conversational AI

## Constitution Check

**GATE: Must pass before Phase 0 research**

- ✅ **Streaming-First**: Will use streaming synthesis (text → audio chunks → immediate playback)
- ✅ **Interruptible <50ms**: NATS for control, sounddevice.stop() for instant stop
- ✅ **sounddevice for Audio**: Using sounddevice OutputStream
- ✅ **NATS for Real-Time Control**: NATS Pub/Sub for interrupt signals
- ✅ **Piper TTS Engine**: Piper subprocess for synthesis
- ✅ **PulseAudio Virtual Mic**: Output to virtual_mic device
- ✅ **MongoDB Change Streams**: Queue processing via change streams
- ✅ **Test-First**: TDD mandatory, tests before implementation
- ✅ **Simplicity**: Single service, no over-engineering

## Project Structure

### Documentation

```text
specs/001-tts-service/
├── spec.md              # Feature specification
├── plan.md              # This file
├── tasks.md             # Task breakdown
└── adr/                 # Architecture decision records (if needed)
```

### Source Code

```text
src/
├── tts/
│   ├── __init__.py
│   ├── main.py              # Service entry point
│   ├── config.py            # Configuration (MongoDB, NATS, Piper, audio)
│   ├── tts_queue.py         # MongoDB change stream listener
│   ├── synthesizer.py       # Piper TTS subprocess manager
│   ├── audio_player.py      # sounddevice OutputStream wrapper
│   ├── interrupt_handler.py # NATS subscriber for interrupt signals
│   └── status_updater.py    # MongoDB status updates

tests/
├── __init__.py
├── contract/
│   ├── test_mongodb_schema.py
│   └── test_nats_protocol.py
├── integration/
│   ├── test_queue_to_audio.py
│   └── test_interruption_flow.py
└── unit/
    ├── test_synthesizer.py
    ├── test_audio_player.py
    └── test_interrupt_handler.py

models/
└── tts_queue.py             # Pydantic model for TTS queue documents

requirements.txt             # Python dependencies
Dockerfile                   # Container build
docker-compose.yml           # Local development (MongoDB, NATS, PulseAudio)
.pytest.ini                  # Pytest configuration
```

**Structure Decision**: Single project with `src/` layout. Tests separated by type (contract, integration, unit).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| NATS + MongoDB | Sub-50ms interruption required | MongoDB alone too slow (50-200ms) |
| sounddevice | Streaming + interrupt control | paplay blocks until file ends |
| Piper subprocess | Offline TTS, no API costs | ElevenLabs requires API key, costs |

## Phase 0: Research Output

### Piper TTS Integration

- Install via pip: `pip install piper-tts`
- Model path: `/app/models/piper/en_US-amy-medium.onnx`
- Command: `piper --model <path> --output-raw`
- Output: PCM s16le, 22050Hz, mono
- Chunk size: 4096 bytes (~93ms audio)

### NATS Setup

- Server: `nats://localhost:4222`
- Publish subject: `tts.interrupt`
- Subscribe: `await nc.subscribe("tts.interrupt", cb=handler)`
- Message payload: JSON `{ "session_id": "..." }` or empty

### MongoDB Schema (tts_queue)

```json
{
  "_id": "uuid",
  "session_id": "sess_123",
  "text": "Hello, how are you?",
  "status": "pending|playing|completed|interrupted|failed",
  "priority": "normal|high",
  "created_at": 1700000000,
  "started_at": 1700000001,
  "completed_at": 1700000003,
  "interrupted_at": null,
  "error_message": null
}
```

### sounddevice Configuration

```python
stream = sd.OutputStream(
    samplerate=22050,
    channels=1,
    dtype='int16',
    device='virtual_mic'
)
```

## Quickstart

```bash
# 1. Start dependencies
docker-compose up -d mongodb nats pulseaudio

# 2. Install dependencies
pip install -r requirements.txt

# 3. Download Piper model
mkdir -p models/piper
wget -O models/piper/en_US-amy-medium.onnx <model-url>

# 4. Set environment
export MONGODB_URI=mongodb://localhost:27017
export NATS_URI=nats://localhost:4222
export PULSE_SERVER=unix:/run/user/1000/pulse/native
export VIRTUAL_MIC=virtual_mic

# 5. Run tests
pytest

# 6. Run service
python -m src.tts.main
```

## Contracts

### MongoDB Contract

- Collection: `tts_queue`
- Change Stream: Watch for `insert` operations
- Update: Modify document status in-place

### NATS Contract

- Subject: `tts.interrupt`
- Publisher: STT service or Control service
- Subscriber: TTS service
- Payload: Optional JSON with `session_id`

### Audio Contract

- Format: PCM 16-bit signed little-endian (s16le)
- Sample Rate: 22050 Hz
- Channels: 1 (mono)
- Output Device: PulseAudio `virtual_mic`

### Piper Contract

- Input: UTF-8 text via stdin
- Output: PCM audio via stdout
- Exit Code: 0 on success, non-zero on error
