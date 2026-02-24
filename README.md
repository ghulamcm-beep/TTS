# TTS Service

A real-time Text-to-Speech microservice for conversational AI applications. Monitors MongoDB for synthesis requests, streams audio via ElevenLabs, and outputs to a PulseAudio virtual microphone — with sub-50ms interruption support.

## Architecture

```
MongoDB (interviews.transcripts)
    ↓ [Change Streams]
TranscriptListener → ElevenLabsSynthesizer → AudioPlayer → PulseAudio (virtual_mic)
    ↑                                              ↑
NATS (tts.interrupt) → InterruptHandler ───────────
```

**Services:**
| Service | Role |
|---|---|
| MongoDB 7.0 | Persistent queue via Change Streams |
| NATS 2.10 | Real-time interrupt pub/sub |
| PulseAudio | Virtual microphone output |
| TTS App | Python orchestration service |

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env and set ELEVENLABS_API_KEY

# 2. Start all services
docker compose up
```

The service is ready when MongoDB replica set initialization completes. Insert a document into `interviews.transcripts` with `speaker="agent"` and `audio_url=null` to trigger synthesis.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ELEVENLABS_API_KEY` | *(required)* | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` | Voice ID (Rachel) |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` | Model (lowest latency) |
| `MONGODB_URI` | `mongodb://localhost:27017/?replicaSet=rs0` | MongoDB connection |
| `MONGODB_DB` | `interviews` | Database name |
| `TRANSCRIPTS_COLLECTION` | `transcripts` | Collection name |
| `NATS_URI` | *(optional)* | NATS server — interrupt disabled if blank |
| `AUDIO_DEVICE_ID` | *(optional)* | sounddevice ID — uses system default |
| `PULSE_SERVER` | *(optional)* | PulseAudio socket path |
| `VIRTUAL_MIC` | *(optional)* | Virtual microphone device name |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Local Development

```bash
# Install dependencies
uv sync

# Run service (requires local MongoDB, NATS, PulseAudio)
uv run python -m src.tts.main

# Run tests
pytest tests/
```

Tests are organized under `tests/unit/`, `tests/integration/`, and `tests/contract/`.

## Key Design Decisions

- **Streaming-first** — Audio chunks flow directly from ElevenLabs to sounddevice with no intermediate buffering, targeting <300ms first-audio latency.
- **MongoDB Change Streams** — Watches for inserts rather than polling; provides guaranteed delivery and auto-reconnect with exponential backoff.
- **NATS interrupts** — Stop signals published to `tts.interrupt` close the HTTP stream and halt playback within <50ms.
- **GridFS caching** — Synthesized PCM audio is stored in GridFS for cache-hit playback on repeated phrases.
- **Graceful degradation** — Service starts without interrupt support if NATS is unavailable; synthesis continues even if the audio device is unavailable.

## Tech Stack

- Python 3.11+, `motor`, `nats-py`, `httpx`, `sounddevice`, `numpy`, `pydantic`
- Docker, MongoDB 7.0 (replica set), NATS JetStream, PulseAudio
- Package manager: `uv`
