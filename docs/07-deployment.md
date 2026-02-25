# 07 — Deployment

---

## Local Development (Windows)

No Docker required. MongoDB runs locally; audio plays through a real speaker or headphone.

### Prerequisites

- Python 3.11+, `uv`
- MongoDB 7.0 running locally as replica set (see [Building from Scratch §Step 2](./03-building-from-scratch.md))
- ElevenLabs API key

### Start

```bash
uv run python -m src.tts.main
```

### Configuration (.env)

```env
ELEVENLABS_API_KEY=sk_your_key
MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0
AUDIO_DEVICE_ID=4        # optional: set to your headphone/speaker device ID
NATS_URI=                # leave empty — interrupt disabled, fine for testing
LOG_LEVEL=INFO
```

### Notes

- If `AUDIO_DEVICE_ID` is set to a device that's offline (headphones unplugged), the service falls back to the system default automatically
- Audio plays through Windows speakers/headphones directly via PortAudio
- `Ctrl+C` stops the service gracefully

---

## Local Development (Linux)

Identical to Windows except PulseAudio is available and can be used.

### With real speakers

Same as Windows — set `AUDIO_DEVICE_ID` or leave blank for default.

### With PulseAudio virtual mic (for integration testing)

```bash
# Create a virtual sink
pactl load-module module-null-sink sink_name=virtual_mic sink_properties=device.description=virtual_mic

# Verify
pactl list sinks short
# should show: virtual_mic

# Set VIRTUAL_MIC in .env
VIRTUAL_MIC=virtual_mic
AUDIO_DEVICE_ID=          # leave blank — virtual_mic found by name
PULSE_SERVER=unix:/run/user/1000/pulse/native
```

---

## Docker Compose — Full Stack

Runs all five services: MongoDB, NATS, PulseAudio, mongo-init, TTS.

### First-Time Setup

```bash
# Build TTS image (only needed first time or after code changes)
docker compose build

# Start all services
docker compose up
```

### Service Startup Order

```
mongodb (health check: mongosh ping)
   │
   └── mongo-init (initialises replica set, exits)
   └── tts (waits for mongodb healthy)

nats (starts immediately)
   └── tts (waits for nats started)

pulseaudio (starts immediately)
   └── tts (waits for pulseaudio started)
```

The `tts` container starts after all dependencies are ready. Full stack ready time: ~30 seconds.

### Rebuild After Code Changes

```bash
docker compose build tts
docker compose up -d tts     # restart only TTS, keep MongoDB/NATS running
```

### Environment in Docker

`.env` is loaded via `env_file: .env` for secrets (API key). Container-internal addresses are injected via `environment:` block, overriding `.env`:

```yaml
# docker-compose.yml
tts:
  env_file:
    - .env                          # loads ELEVENLABS_API_KEY from .env
  environment:
    MONGODB_URI: mongodb://mongodb:27017/?replicaSet=rs0   # internal Docker network
    NATS_URI: nats://nats:4222                              # internal Docker network
    PULSE_SERVER: unix:/run/pulse/native                   # shared volume
    VIRTUAL_MIC: virtual_mic
```

Never hard-code `ELEVENLABS_API_KEY` in `docker-compose.yml`.

### Audio in Docker

Audio output goes to the PulseAudio container (`virtual_mic` device). This is a Linux virtual sink — not your Windows speakers. In the full meeting bot system, the headless browser connects to this same PulseAudio instance and reads from `virtual_mic` as its microphone input.

To verify audio is flowing into the virtual mic:
```bash
docker compose exec pulseaudio pactl list sink-inputs
```

### Useful Commands

```bash
# View all logs
docker compose logs -f

# View TTS service logs only
docker compose logs -f tts

# Trigger synthesis
docker compose exec mongodb mongosh interviews --eval "
  db.transcripts.insertOne({
    interview_id:'test', speaker:'agent',
    text:'Hello from Docker.', audio_url:null, timestamp:new Date()
  })
"

# Send an interrupt
docker compose exec nats nats pub tts.interrupt '{}'

# Stop and preserve data
docker compose down

# Stop and wipe all data (MongoDB volumes)
docker compose down -v

# Restart only TTS
docker compose restart tts
```

---

## Dockerfile Reference

```dockerfile
FROM python:3.11-slim

# PortAudio (sounddevice) + PulseAudio client libs
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    libpulse-dev \
    pulseaudio-utils \
    curl

# uv package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Cache-efficient: install deps first (only reinstall if pyproject.toml changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Then copy source (changes here don't invalidate the dep layer)
COPY src/ ./src/
COPY models/ ./models/

ENV PYTHONPATH=/app

CMD ["uv", "run", "python", "-m", "src.tts.main"]
```

**Key decisions**:
- `--frozen`: uses exact versions from `uv.lock`, not latest
- `--no-dev`: excludes pytest and other dev tools from the image
- Source copied after deps: faster rebuilds when only source changes

---

## Production Considerations

### Secrets Management

Never commit `.env` with real API keys. In production:

```bash
# Use environment variables injected by your platform
export ELEVENLABS_API_KEY=$(vault kv get -field=key secret/elevenlabs)

# Or use Docker secrets
docker secret create elevenlabs_key ./key.txt
```

### Process Supervision

The TTS service is a long-running process. In production, wrap it with a supervisor:

```yaml
# docker-compose.yml addition
tts:
  restart: unless-stopped    # auto-restart on crash
```

Or use systemd:
```ini
[Service]
ExecStart=uv run python -m src.tts.main
Restart=always
RestartSec=5
```

### MongoDB Replica Set in Production

A single-node replica set (`rs0` with one member) is sufficient for Change Streams. For high availability, use a 3-node replica set:

```javascript
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongo1:27017" },
    { _id: 1, host: "mongo2:27017" },
    { _id: 2, host: "mongo3:27017" }
  ]
})
```

### Observability

Logs are structured JSON — ship to any aggregator:

```bash
# Pipe to Datadog agent
uv run python -m src.tts.main 2>&1 | datadog-agent

# Or in Docker
tts:
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"
```

Key log fields to alert on:
- `level: ERROR` with `message` containing `ElevenLabs` → API failure
- `level: ERROR` with `message` containing `MongoDB` → database issue
- `level: WARNING` with `Audio playback unavailable` → audio device problem
- `level: ERROR` with `Max MongoDB reconnection attempts reached` → service stalled, needs restart
