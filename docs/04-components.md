# 04 — Component Reference

Each module in `src/tts/` has a single, well-defined responsibility. This document describes what each does, how it works internally, and what to know when modifying it.

---

## TTSService — `src/tts/main.py`

**Role**: Top-level orchestrator. Owns all components, runs the main loop, coordinates synthesis.

### Lifecycle

```
TTSService.__init__()
  ├── AsyncIOMotorClient(config.mongodb_uri)
  ├── TranscriptListener(client)
  ├── ElevenLabsSynthesizer()
  ├── AudioPlayer()
  ├── InterruptHandler()
  └── TranscriptUpdater(client)

TTSService.start()
  ├── [optional] InterruptHandler.connect()  ← only if NATS_URI set
  └── async for doc in TranscriptListener.watch():
        ├── InterruptHandler.reset()          ← clear previous stop_event
        └── _process_transcript(doc)

TTSService.stop()
  ├── [optional] InterruptHandler.close()
  ├── TranscriptListener.close()
  ├── ElevenLabsSynthesizer.close()
  └── mongo_client.close()
```

### `_process_transcript(doc)`

This is the core synthesis method. Two paths:

**Cache hit** (`doc.audio_data` is not None):
```python
await AudioPlayer.play(
    _chunks_from_bytes(doc.audio_data),
    interrupt_handler.stop_event
)
await TranscriptUpdater.mark_played(doc.id, doc.audio_data)
```

**Cache miss** (`doc.audio_data` is None):
```python
audio_buffer = []
raw_chunks = ElevenLabsSynthesizer.synthesize(doc.text)
teed = _buffered(raw_chunks, audio_buffer)   # tee: play AND accumulate

try:
    await AudioPlayer.play(teed, interrupt_handler.stop_event)
except Exception:
    # Audio device unavailable (container without PulseAudio)
    # Drain the generator so audio_buffer still fills
    async for _ in teed:
        pass

audio_data = b"".join(audio_buffer)
await TranscriptUpdater.mark_played(doc.id, audio_data)
```

**Key design**: The `_buffered()` tee means audio plays AND is collected simultaneously. If audio fails, synthesis still completes and audio is saved to GridFS.

### Signal Handling

On `SIGTERM`/`SIGINT`, `service.stop()` is called gracefully. Windows does not support `loop.add_signal_handler()` for all signals — the code catches this and falls back to `KeyboardInterrupt`.

---

## TranscriptListener — `src/tts/tts_queue.py`

**Role**: Watches MongoDB for new agent utterances using Change Streams.

### How Change Streams Work

MongoDB Change Streams provide a push-based notification when a document is inserted, updated, or deleted. Unlike polling, the driver holds an open cursor on the oplog and receives events as they happen.

```python
pipeline = [{
    "$match": {
        "operationType": "insert",
        "fullDocument.speaker": "agent",
        "fullDocument.audio_url": None,
    }
}]

async with collection.watch(pipeline, full_document="updateLookup") as stream:
    async for change in stream:
        full_doc = change.get("fullDocument")
        doc = TranscriptDocument.model_validate(full_doc)
        yield doc
```

The pipeline filters so only relevant documents are delivered — no code runs for candidate speech or documents that already have audio.

### Reconnection

On any Change Stream error (MongoDB restart, network blip), the listener retries with exponential backoff:

```
attempt 1: wait 1.0s
attempt 2: wait 2.0s
attempt 3: wait 4.0s
...
max: 30.0s per attempt, 5 attempts total
```

After 5 failed attempts, the service logs an error and exits the watch loop. The service process can then be restarted by the container orchestrator.

**Requirement**: MongoDB must be a replica set (`replSet rs0`). Standalone mongod does not support Change Streams.

---

## ElevenLabsSynthesizer — `src/tts/synthesizer.py`

**Role**: Streams raw PCM audio from ElevenLabs API via httpx.

### API Call

```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream
     ?output_format=pcm_22050

Headers:
  xi-api-key: {ELEVENLABS_API_KEY}
  Content-Type: application/json

Body:
  {"text": "...", "model_id": "eleven_flash_v2_5"}

Response: binary stream of raw 16-bit signed PCM at 22050Hz mono
```

### Streaming Implementation

```python
async with httpx.AsyncClient(timeout=config.elevenlabs_connect_timeout) as client:
    async with client.stream("POST", url, headers=headers, json=body) as response:
        _raise_for_status(response)
        async for chunk in response.aiter_bytes(chunk_size=config.chunk_size):
            yield chunk
```

Each chunk is 4096 bytes by default = 2048 int16 samples = ~93ms of audio. Chunks arrive as fast as ElevenLabs generates them.

### Error Taxonomy

| HTTP Status | Exception | Behaviour |
|---|---|---|
| 401 | `ElevenLabsAuthError` | Re-raised; service logs and marks doc failed |
| 429 | `ElevenLabsRateLimitError` | Re-raised; service logs and marks doc failed |
| 5xx | `ElevenLabsServerError` | Re-raised; service logs and marks doc failed |
| Timeout | `ElevenLabsNetworkError` | Re-raised; service logs and marks doc failed |
| Network error | `ElevenLabsNetworkError` | Re-raised; service logs and marks doc failed |

### Statelessness

`ElevenLabsSynthesizer` holds no state between calls. Each `synthesize()` call opens a fresh `httpx.AsyncClient`. A failed synthesis does not affect the next one.

### `_raise_for_status(response)` — `src/tts/synthesizer.py:19`

Helper that checks HTTP status before entering the chunk loop. Must be called before `aiter_bytes()` because the response status arrives in headers, before body chunks.

---

## AudioPlayer — `src/tts/audio_player.py`

**Role**: Streams PCM chunks to a sounddevice OutputStream, handling device selection and mono→stereo upmixing.

### Device Resolution Order

```
1. AUDIO_DEVICE_ID env var set?
   └── validate with sd.query_devices(id, kind="output")
       ├── OK → use it
       └── FAIL → warning + fall through

2. virtual_mic in device names?
   └── iterate sd.query_devices()
       ├── found → use matching index
       └── not found → fall through

3. None → sounddevice system default
```

### Opening the Stream

```python
self._stream = sd.OutputStream(
    device=device_id,       # int or None
    samplerate=22050,       # matches ElevenLabs pcm_22050
    channels=out_channels,  # 1 (mono) or 2 (stereo)
    dtype="int16",          # matches ElevenLabs 16-bit PCM
    blocksize=2048,         # chunk_size // 2 = 4096 // 2
)
```

If opening fails (e.g. device offline), the player automatically retries with `device=None` (system default) before propagating the error.

### Mono → Stereo Upmixing

ElevenLabs outputs mono PCM. Most speaker devices require stereo. If `max_output_channels >= 2`, the player upmixes by duplicating the channel:

```python
mono = np.frombuffer(chunk, dtype=np.int16)      # shape: (N,)
stereo = np.column_stack((mono, mono))            # shape: (N, 2)
self._stream.write(stereo)
```

### Interruption

After every chunk write, the player checks `stop_event`:

```python
async for chunk in audio_chunks:
    if stop_event.is_set():
        break
```

Since chunks are ~93ms of audio, the maximum delay between an interrupt signal and audio stopping is one chunk cycle plus sounddevice's internal buffer drain (~4ms). Total: <100ms in worst case, typically <50ms.

---

## InterruptHandler — `src/tts/interrupt_handler.py`

**Role**: Subscribes to NATS `tts.interrupt` subject and exposes an `asyncio.Event` that AudioPlayer checks.

### NATS Connection

```python
self._nc = await nats.connect(
    config.nats_uri,
    max_reconnect_attempts=5,
    reconnect_time_wait=2,
    error_cb=...,
    disconnected_cb=...,
    reconnected_cb=...,
)
self._subscription = await self._nc.subscribe(
    "tts.interrupt",
    cb=self._handle_interrupt,
)
```

The NATS client automatically reconnects on transient disconnections (up to 5 attempts, 2s between each).

### Interrupt Message Format

```json
// Broadcast — stops any active synthesis
{}

// Targeted — stops synthesis for a specific session
{"session_id": "sess_001"}
```

The handler currently treats both identically (sets the stop_event unconditionally). Session-targeted interrupts are a future enhancement.

### Event Lifecycle

```
InterruptHandler.reset()           ← called before each utterance starts
  └── self._stop_event.clear()

[synthesis in progress]

NATS message received
  └── self._stop_event.set()

AudioPlayer detects stop_event
  └── breaks out of chunk loop

InterruptHandler.reset()           ← called before next utterance
  └── self._stop_event.clear()
```

### Optional Feature

When `NATS_URI` is empty in `.env`, `InterruptHandler.connect()` is never called. `stop_event` still exists but is never set by NATS. This means synthesis runs to completion with no interrupt capability — acceptable for local testing.

---

## TranscriptUpdater — `src/tts/status_updater.py`

**Role**: Uploads synthesised PCM audio to GridFS and updates the transcript document with the GridFS file ID.

### GridFS Upload

```python
file_id = await self._bucket.upload_from_stream(
    f"transcript_{document_id}.pcm",
    audio_data,
    metadata={
        "transcript_id": str(document_id),
        "format": "pcm_22050",
        "sample_rate": 22050,
        "channels": 1,
        "bits": 16,
    }
)
```

GridFS splits the bytes into 255KB chunks stored in `audio.chunks`, with a file entry in `audio.files`.

### Document Update

```python
await self.collection.update_one(
    {"_id": document_id},
    {"$set": {"audio_url": str(file_id)}}
)
```

`audio_url` is used as a sentinel:
- `null` — not yet processed (triggers Change Stream)
- `"played"` — processed but no audio saved (e.g. error path, or container without audio device)
- `"<ObjectId>"` — GridFS file ID of the stored PCM

---

## Config — `src/tts/config.py`

**Role**: Single frozen dataclass holding all configuration loaded from environment variables at startup via `load_dotenv()`.

`config` is a module-level singleton — all modules import it as `from .config import config`. Changing `.env` requires a service restart.

See [05 — Configuration](./05-configuration.md) for the full variable reference.

---

## Exceptions — `src/tts/exceptions.py`

**Role**: Typed exception hierarchy for ElevenLabs API errors.

```
Exception
└── ElevenLabsError(message, status_code=None)
    ├── ElevenLabsAuthError        (401)
    ├── ElevenLabsRateLimitError   (429)
    ├── ElevenLabsServerError      (5xx)
    └── ElevenLabsNetworkError     (timeout / connection failure)
```

All exceptions carry `status_code` for structured logging. `ElevenLabsNetworkError` may have `status_code=None` since it is not an HTTP error.

---

## Data Models — `models/tts_queue.py`

**Role**: Pydantic v2 schemas shared between the TTS service and the AI pipeline.

### `TranscriptDocument`

The primary document the TTS service reads from MongoDB:

```python
class TranscriptDocument(BaseModel):
    id: Any              # MongoDB _id (ObjectId or string)
    interview_id: str    # groups utterances by interview session
    speaker: str         # "agent" | "candidate"
    text: str            # the text to synthesise
    audio_url: Optional[str] = None   # null → to-do; str → done
    audio_data: Optional[bytes] = None  # inline PCM (rarely populated)
    audio_format: Optional[str] = None  # "pcm_22050"
    timestamp: Optional[datetime] = None

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}
```

The `_id` alias is mapped to `id` via `Field(alias="_id")` with `populate_by_name=True`.

### `TTSQueueDocument`

Legacy schema from the original Piper-based TTS service. Retained only for contract tests — not used in the live pipeline.

---

## Logging — `src/tts/logging_config.py`

All logs are emitted as JSON to stdout:

```json
{
  "timestamp": "2026-02-24T09:59:04.076579+00:00",
  "level": "INFO",
  "logger": "src.tts.synthesizer",
  "message": "ElevenLabs synthesis complete: 25 chunks"
}
```

This makes logs parseable by any structured logging platform (Datadog, CloudWatch, ELK, etc.).

`setup_logging(level)` is called once at startup from `main.py`. The level defaults to `INFO` and is overridden by the `LOG_LEVEL` environment variable.
