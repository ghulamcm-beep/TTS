# 03 — Building the System from Scratch

This guide walks through building and running the TTS service from zero. By the end you will have a working service that synthesises speech from MongoDB documents and plays audio.

---

## Prerequisites

### Required

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime |
| uv | latest | Package manager & runner |
| MongoDB | 7.0 | Persistent queue (replica set required) |
| Git | any | Source control |

### Optional

| Tool | Version | Purpose |
|---|---|---|
| Docker + Docker Compose | 24+ | Full containerised stack |
| NATS | 2.10 | Interrupt signals (<50ms stop latency) |
| PulseAudio | any | Virtual mic output (Linux production only) |

### Install uv (if not present)

```bash
# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

---

## Step 1 — Clone and Install

```bash
git clone <your-repo-url>
cd TTS

# Create virtual environment and install all dependencies
uv sync
```

This installs:
- `motor` — async MongoDB driver
- `nats-py` — NATS client
- `httpx` — async HTTP (ElevenLabs streaming)
- `sounddevice` — PortAudio wrapper (audio output)
- `numpy` — PCM buffer processing
- `pydantic` — data validation
- `python-dotenv` — env file loading

Dev dependencies (tests):
- `pytest`, `pytest-asyncio`, `pytest-mock`

---

## Step 2 — Configure MongoDB with Replica Set

Change Streams require a replica set. Even for local single-node development you must enable this.

### Option A — Docker (easiest)

```bash
# Start MongoDB with replica set enabled
docker run -d \
  --name mongo \
  -p 27017:27017 \
  mongo:7.0 \
  mongod --replSet rs0 --bind_ip_all

# Wait ~5 seconds, then initialise the replica set
docker exec mongo mongosh --eval \
  "rs.initiate({_id:'rs0', members:[{_id:0, host:'localhost:27017'}]})"
```

### Option B — Local mongod

Edit your `mongod.conf`:

```yaml
replication:
  replSetName: "rs0"
```

Then initialise:

```bash
mongosh --eval "rs.initiate({_id:'rs0', members:[{_id:0, host:'localhost:27017'}]})"
```

### Verify replica set is working

```bash
mongosh --eval "rs.status().ok"
# Should print: 1
```

---

## Step 3 — Get an ElevenLabs API Key

1. Sign up at https://elevenlabs.io
2. Go to Profile → API Keys
3. Create a new key and copy it

Free tier provides 10,000 characters/month. `eleven_flash_v2_5` is the lowest-cost, lowest-latency model.

---

## Step 4 — Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required
ELEVENLABS_API_KEY=sk_your_key_here

# MongoDB (replica set required)
MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0
MONGODB_DB=interviews
TRANSCRIPTS_COLLECTION=transcripts

# NATS — leave blank to disable interrupt feature
NATS_URI=

# Audio device
# Leave blank to use system default
# Run: uv run python -c "import sounddevice as sd; print(sd.query_devices())"
# to list devices and find your output device ID
AUDIO_DEVICE_ID=

# PulseAudio (Linux/container only)
PULSE_SERVER=unix:/run/user/1000/pulse/native
VIRTUAL_MIC=virtual_mic

# Logging
LOG_LEVEL=INFO
```

### Find your audio device ID (Windows/Linux local)

```bash
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

Example output:
```
  0 Microsoft Sound Mapper - Input, MME (2 in, 0 out)
  1 Microphone (Realtek Audio), MME (2 in, 0 out)
> 2 Microsoft Sound Mapper - Output, MME (0 in, 2 out)
  3 Speakers (Realtek Audio), MME (0 in, 2 out)
  4 Headphone (Realtek Audio), MME (0 in, 2 out)
```

Set `AUDIO_DEVICE_ID=3` for speakers, `AUDIO_DEVICE_ID=4` for headphones, or leave blank for system default.

---

## Step 5 — Run the Service

```bash
uv run python -m src.tts.main
```

Expected startup logs:

```json
{"level":"INFO","message":"Starting TTS Service..."}
{"level":"INFO","message":"NATS_URI not set — interrupt feature disabled"}
{"level":"INFO","message":"Watching interviews.transcripts for agent utterances"}
```

The service is now listening for documents.

---

## Step 6 — Trigger a Synthesis

In a separate terminal:

```bash
mongosh interviews --eval "
  db.transcripts.insertOne({
    interview_id: 'test_001',
    speaker: 'agent',
    text: 'Hello, I am your AI interview assistant.',
    audio_url: null,
    timestamp: new Date()
  })
"
```

Expected service logs:

```json
{"level":"INFO","message":"New transcript: interview=test_001 chars=40"}
{"level":"INFO","message":"Processing transcript: interview=test_001 chars=40"}
{"level":"INFO","message":"Using system default output device"}
{"level":"INFO","message":"Opening audio stream: device=None channels=2"}
{"level":"INFO","message":"Synthesizing via ElevenLabs: voice=21m00Tcm4TlvDq8ikWAM model=eleven_flash_v2_5 chars=40"}
{"level":"INFO","message":"ElevenLabs synthesis complete: 21 chunks"}
{"level":"INFO","message":"Playback complete"}
{"level":"INFO","message":"Audio stored in GridFS: 6abc... (82.0 KB)"}
{"level":"INFO","message":"Transcript completed: 6xyz... audio saved 82.0 KB"}
```

You should hear the audio through your configured output device.

---

## Step 7 — Measure Response Time

```bash
uv run python scripts/benchmark.py

# Custom text
uv run python scripts/benchmark.py --text "The quick brown fox jumped over the lazy dog"
```

Expected output:

```
[benchmark] Total latency    : 1157ms
[benchmark] Synthesis + save : 1129ms
[benchmark] Chars/second     : 38.0
```

---

## Step 8 — Play Audio from Database

```bash
uv run python scripts/play_from_db.py
```

Lists synthesised audio stored in GridFS. Enter a number to play it back locally.

---

## Step 9 — Run Tests

```bash
# All tests
uv run pytest tests/ -v

# Unit tests only (no infrastructure required)
uv run pytest tests/unit/ -v

# With coverage
uv run pytest tests/ --tb=short
```

Expected: 42 passed, 1 skipped (NATS format test skipped when NATS_URI is empty).

---

## Full Docker Stack (Optional)

If you want to run everything in containers (MongoDB, NATS, PulseAudio, TTS service):

```bash
# Build the TTS image (only needed the first time or after code changes)
docker compose build

# Start all services
docker compose up

# Watch logs
docker compose logs -f tts

# Stop everything
docker compose down

# Wipe all data
docker compose down -v
```

Services started by `docker compose up`:

| Service | Image | Port |
|---|---|---|
| `mongodb` | `mongo:7.0` | 27017 |
| `mongo-init` | `mongo:7.0` | — |
| `nats` | `nats:2.10-alpine` | 4222, 8222 |
| `pulseaudio` | `x11docker-pulseaudio` | 4713 |
| `tts` | built from `Dockerfile` | — |

The `mongo-init` container runs once to initialise the replica set and exits. The TTS container waits for MongoDB to be healthy before starting.

### Trigger synthesis in Docker

```bash
docker compose exec mongodb mongosh interviews --eval "
  db.transcripts.insertOne({
    interview_id: 'test_001',
    speaker: 'agent',
    text: 'Hello from the containerised TTS pipeline.',
    audio_url: null,
    timestamp: new Date()
  })
"
```

Audio goes to the PulseAudio virtual mic inside the container — not your local speakers.

---

## Directory Structure Reference

```
TTS/
├── src/tts/              Python source — TTS service modules
├── models/               Pydantic data models (shared with AI pipeline)
├── tests/
│   ├── unit/             Unit tests (no infrastructure)
│   ├── integration/      Integration tests (mocked infrastructure)
│   └── contract/         Contract tests (schema + protocol validation)
├── scripts/
│   ├── benchmark.py      End-to-end latency measurement
│   └── play_from_db.py   Play GridFS audio locally
├── docs/                 This documentation
├── specs/                Feature specifications and architecture plans
├── history/              Prompt History Records and ADRs
├── .specify/             SDD templates and constitution
├── Dockerfile            TTS container image
├── docker-compose.yml    Full stack container configuration
├── pyproject.toml        Python project + dependencies
├── pytest.ini            Test configuration
└── .env.example          Environment variable template
```
