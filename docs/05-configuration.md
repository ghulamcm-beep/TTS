# 05 — Configuration Reference

All configuration is loaded from environment variables. The `.env` file is loaded automatically when the service starts (via `python-dotenv`). In Docker, values are provided via `docker-compose.yml` environment blocks.

---

## How Configuration is Loaded

```
.env file → load_dotenv() → os.getenv() → Config dataclass → config singleton
```

`load_dotenv()` runs at import time in `src/tts/config.py`. Every module that does `from .config import config` gets the same singleton. Changing `.env` requires a service restart.

In Docker Compose, the `environment:` block in `docker-compose.yml` overrides values from the `.env` file (which is loaded via `env_file: .env`).

---

## Environment Variables

### ElevenLabs

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `ELEVENLABS_API_KEY` | string | `""` | **Yes** | API key from elevenlabs.io. Never logged. |
| `ELEVENLABS_VOICE_ID` | string | `21m00Tcm4TlvDq8ikWAM` | No | Voice ID. Default is Rachel (English, female). |
| `ELEVENLABS_MODEL_ID` | string | `eleven_flash_v2_5` | No | Model. `eleven_flash_v2_5` = lowest latency. |
| `ELEVENLABS_OUTPUT_FORMAT` | string | `pcm_22050` | No | Audio format. Must match `sample_rate` and `dtype`. Do not change without updating `AudioPlayer`. |

**Voice IDs** — find available voices at: `GET https://api.elevenlabs.io/v1/voices`

**Models**:
| Model | Latency | Quality | Use |
|---|---|---|---|
| `eleven_flash_v2_5` | ~200ms | Good | Default — best for real-time |
| `eleven_turbo_v2_5` | ~300ms | Better | Higher quality, slightly slower |
| `eleven_multilingual_v2` | ~500ms | Best | Multi-language support |

---

### MongoDB

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `MONGODB_URI` | string | `mongodb://localhost:27017/?replicaSet=rs0` | No | Connection string. Must include `?replicaSet=rs0` for Change Streams. |
| `MONGODB_DB` | string | `interviews` | No | Database name. |
| `TRANSCRIPTS_COLLECTION` | string | `transcripts` | No | Collection watched for new agent utterances. |

**Replica Set**: The `?replicaSet=rs0` query parameter is mandatory. Without it, Change Streams raise `OperationFailure: The $changeStream stage is only supported on replica sets`.

**Auth**: If MongoDB requires authentication:
```
MONGODB_URI=mongodb://username:password@localhost:27017/?replicaSet=rs0&authSource=admin
```

---

### NATS

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `NATS_URI` | string | `""` | No | NATS server address. Leave empty to disable interrupt feature. |

**Format**: `nats://host:port` — e.g. `nats://localhost:4222`

When `NATS_URI` is empty:
- The service starts without connecting to NATS
- `stop_event` is never set from external signals
- Synthesis always runs to completion (no mid-sentence interruption)
- Suitable for standalone testing

When `NATS_URI` is set:
- `InterruptHandler.connect()` is called on startup
- Subscribes to `tts.interrupt`
- Any message on that subject stops the current synthesis within <50ms

---

### Audio

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `AUDIO_DEVICE_ID` | integer | `None` | No | sounddevice output device index. Leave blank for system default. |
| `PULSE_SERVER` | string | `unix:/run/user/1000/pulse/native` | No | PulseAudio server socket. Linux/container only. |
| `VIRTUAL_MIC` | string | `virtual_mic` | No | Name of virtual mic device to find by name (fallback when `AUDIO_DEVICE_ID` not set). |

**Device selection logic** (in priority order):
1. If `AUDIO_DEVICE_ID` is set and the device is valid → use it
2. If `AUDIO_DEVICE_ID` device fails validation → log warning, fall through
3. If a device named `VIRTUAL_MIC` exists → use it (Linux/PulseAudio)
4. Otherwise → use sounddevice system default

**List available devices**:
```bash
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

---

### Audio Format Constants

These match the ElevenLabs `pcm_22050` output format. Change only if you change `ELEVENLABS_OUTPUT_FORMAT`.

| Variable | Value | Meaning |
|---|---|---|
| `sample_rate` (hardcoded) | `22050` | 22,050 samples per second |
| `dtype` (hardcoded) | `"int16"` | 16-bit signed integer samples |
| `channels` (hardcoded) | `1` | Mono source audio |
| `chunk_size` (hardcoded) | `4096` | Bytes per chunk (2048 samples = ~93ms) |

---

### Performance

| Variable | Value | Description |
|---|---|---|
| `elevenlabs_connect_timeout` (hardcoded) | `10.0s` | httpx connect + first-byte timeout |
| `interruption_latency_ms` (hardcoded) | `50` | Target max interrupt latency |
| `mongo_max_retries` (hardcoded) | `5` | Change Stream reconnect attempts |
| `mongo_retry_base_delay` (hardcoded) | `1.0s` | Initial backoff (doubles each retry) |
| `nats_max_reconnect_attempts` (hardcoded) | `5` | NATS reconnect attempts |

---

### Logging

| Variable | Type | Default | Description |
|---|---|---|---|
| `LOG_LEVEL` | string | `INFO` | Python log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

All logs are structured JSON. Set `LOG_LEVEL=DEBUG` to see httpx request details and raw chunk counts.

---

## Per-Environment Examples

### Local Windows Development

```env
ELEVENLABS_API_KEY=sk_your_key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
ELEVENLABS_MODEL_ID=eleven_flash_v2_5
ELEVENLABS_OUTPUT_FORMAT=pcm_22050

MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0
MONGODB_DB=interviews
TRANSCRIPTS_COLLECTION=transcripts

NATS_URI=

AUDIO_DEVICE_ID=4
LOG_LEVEL=INFO
```

### Local Linux Development

```env
ELEVENLABS_API_KEY=sk_your_key

MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0
MONGODB_DB=interviews
TRANSCRIPTS_COLLECTION=transcripts

NATS_URI=nats://localhost:4222

AUDIO_DEVICE_ID=
PULSE_SERVER=unix:/run/user/1000/pulse/native
VIRTUAL_MIC=virtual_mic

LOG_LEVEL=INFO
```

### Docker (values in docker-compose.yml override .env)

In the container, these are injected via the `environment:` block:
```yaml
environment:
  MONGODB_URI: mongodb://mongodb:27017/?replicaSet=rs0
  NATS_URI: nats://nats:4222
  PULSE_SERVER: unix:/run/pulse/native
  VIRTUAL_MIC: virtual_mic
```

The `.env` file is still loaded (via `env_file: .env`) for `ELEVENLABS_API_KEY` and other secrets that should not be in `docker-compose.yml`.
