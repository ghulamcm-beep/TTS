# 02 — System Architecture

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        TTS SERVICE                              │
│                                                                 │
│  ┌──────────────────┐    ┌───────────────────────────────────┐  │
│  │ TranscriptListener│    │         TTSService                │  │
│  │  (tts_queue.py)  │───▶│         (main.py)                 │  │
│  │                  │    │                                   │  │
│  │ MongoDB Change   │    │  ┌─────────────────────────────┐  │  │
│  │ Stream watcher   │    │  │  ElevenLabsSynthesizer       │  │  │
│  └──────────────────┘    │  │  (synthesizer.py)            │  │  │
│                          │  │  httpx async streaming       │  │  │
│  ┌──────────────────┐    │  └──────────────┬──────────────┘  │  │
│  │ InterruptHandler │    │                 │ PCM chunks       │  │
│  │(interrupt_handler│───▶│  ┌──────────────▼──────────────┐  │  │
│  │      .py)        │    │  │  AudioPlayer                 │  │  │
│  │ NATS subscriber  │    │  │  (audio_player.py)           │  │  │
│  │ stop_event       │    │  │  sounddevice OutputStream    │  │  │
│  └──────────────────┘    │  └──────────────┬──────────────┘  │  │
│                          │                 │                  │  │
│  ┌──────────────────┐    │  ┌──────────────▼──────────────┐  │  │
│  │TranscriptUpdater │◀───│  │  TranscriptUpdater           │  │  │
│  │(status_updater   │    │  │  (status_updater.py)         │  │  │
│  │     .py)         │    │  │  GridFS write + doc update   │  │  │
│  └──────────────────┘    │  └─────────────────────────────┘  │  │
│                          └───────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                           │                    │
         ▼                           ▼                    ▼
   ┌──────────┐               ┌──────────┐         ┌──────────────┐
   │ MongoDB  │               │  NATS    │         │  PulseAudio  │
   │ replica  │               │  2.10    │         │  virtual_mic │
   │ set      │               │          │         │  (Linux)     │
   └──────────┘               └──────────┘         └──────────────┘
```

---

## Data Flow — Full Pipeline

### Synthesis Request (cache miss)

```
1. AI Pipeline writes to MongoDB
   interviews.transcripts.insertOne({
     speaker: "agent", text: "...", audio_url: null
   })

2. TranscriptListener receives change event via Change Stream
   (MongoDB notifies within ~10ms of insert)

3. TTSService._process_transcript() called
   ├── InterruptHandler.reset()           clear previous stop_event
   └── doc.audio_data is None?
       └── YES → cache miss path

4. ElevenLabsSynthesizer.synthesize(text)
   POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream
   ?output_format=pcm_22050
   xi-api-key: {ELEVENLABS_API_KEY}
   {"text": "...", "model_id": "eleven_flash_v2_5"}

5. HTTP response streams in chunks (raw PCM bytes)
   Each chunk: 4096 bytes = ~46ms of audio at 22050Hz 16-bit

6. Each chunk is teed:
   ├── → AudioPlayer.play()     (to speakers / virtual mic)
   └── → audio_buffer[]         (accumulate for GridFS)

7. AudioPlayer writes to sounddevice.OutputStream
   mono PCM → upmixed to stereo if device requires it
   (PulseAudio: check stop_event after each chunk)

8. After stream ends:
   TranscriptUpdater.mark_played(doc_id, audio_data)
   ├── GridFS.upload_from_stream(pcm_bytes)  → file_id
   └── collection.update_one({audio_url: str(file_id)})
```

### Synthesis Request (cache hit)

```
1. AI Pipeline writes doc with audio_data already present (rare)
   OR future: TranscriptListener fetches GridFS audio before yield

2. TTSService._process_transcript()
   └── doc.audio_data is not None → cache hit path

3. AudioPlayer.play(_chunks_from_bytes(doc.audio_data), ...)
   No ElevenLabs call — plays raw PCM from DB directly

4. TranscriptUpdater.mark_played(doc_id, doc.audio_data)
```

### Interruption Flow

```
External system publishes to NATS:
  nats.publish("tts.interrupt", b'{"session_id": "sess_001"}')
  OR b''  (broadcast — stops any active synthesis)

InterruptHandler._handle_interrupt(msg)
  └── self._stop_event.set()

AudioPlayer.play() — after current chunk write:
  if stop_event.is_set():
      break  ← exits chunk loop

ElevenLabsSynthesizer.synthesize() — httpx stream:
  chunk loop exits (generator abandoned) → HTTP connection closes

Total latency: chunk_cycle (≤93ms worst case, typically less) + sounddevice drain (≤4ms)
Note: ElevenLabs may stream smaller chunks in practice, reducing interrupt latency
```

---

## Design Decisions and Rationale

### 1. MongoDB Change Streams (not polling)

**Decision**: Watch `interviews.transcripts` with a Change Stream pipeline.

**Why not polling?**
- Polling adds latency equal to poll interval (100ms–1s typically)
- Polling wastes DB connections on empty reads
- Change Streams push exactly when a document is inserted

**Why MongoDB?** The AI pipeline already writes there; no extra broker needed for this integration point.

**Constraint**: Requires a replica set (`--replSet rs0`). A standalone mongod does not support Change Streams.

---

### 2. ElevenLabs over Local TTS (Piper)

**Decision**: Replace Piper TTS subprocess with ElevenLabs HTTP streaming API.

| | Piper (local) | ElevenLabs |
|---|---|---|
| Latency (first chunk) | ~80ms | ~200–400ms (network) |
| Voice quality | Robotic | Human-grade |
| Resource usage | 1 CPU core, 200MB RAM | None (API) |
| Interruption | Kill subprocess | Close HTTP stream |
| Cost | Free | API credits |

**Chosen**: ElevenLabs — quality matters more than latency for a meeting bot. 300ms is imperceptible in conversation.

**Model**: `eleven_flash_v2_5` — lowest latency model in the ElevenLabs lineup.
**Format**: `pcm_22050` — raw signed 16-bit PCM at 22050Hz. No decoding step; plays directly into sounddevice.

---

### 3. NATS for Interrupt Signals (not MongoDB)

**Decision**: Interrupt via NATS pub/sub, not by writing a flag to MongoDB.

**Why not MongoDB?**
- MongoDB polling for interrupt flag adds 50–500ms latency (unacceptable)
- Change Streams for a flag field are heavier than a simple pub/sub message

**Why NATS?**
- Pub/sub push: interrupt received within 1–5ms of publish
- Zero persistent state required for control signals
- `nats-py` is async-native

**Optional**: NATS is not required. When `NATS_URI` is empty, the service starts without interrupt capability. This enables simple standalone testing without infrastructure.

---

### 4. Streaming Audio (not buffering)

**Decision**: Stream chunks from ElevenLabs → sounddevice without buffering the full audio first.

**Why?**
- Buffering adds 1–3 seconds of silence before first audio
- Streaming gives first audio within 300ms of request
- Interruption can happen at chunk boundaries (every ~46ms) instead of requiring full buffer discard

**Trade-off**: If ElevenLabs connection drops mid-stream, audio cuts off. Acceptable — the service logs the error and moves to the next utterance.

---

### 5. GridFS for Audio Storage (not inline documents)

**Decision**: Store synthesised PCM in MongoDB GridFS (`audio` bucket), reference via `audio_url` field.

**Why not inline in the document?**
- A 10-second utterance is ~880KB of PCM; MongoDB documents are limited to 16MB but large inline blobs slow down all collection operations
- GridFS chunks to 255KB pieces; efficient for large binary data

**Why store at all?**
- Audit trail: every utterance the bot spoke is preserved
- Cache: if the same text is requested again, play from GridFS without hitting ElevenLabs API

---

## Latency Budget

```
MongoDB insert detected      ~10ms   (Change Stream push)
ElevenLabs API round-trip   ~200ms   (DNS + TLS + server processing)
First chunk streamed         ~300ms   (total: insert → first audio)
Interruption latency          <50ms   (NATS push + chunk cycle; ElevenLabs chunks vary in size)
Chunk duration (4096 bytes)   ~93ms   (4096 bytes ÷ 2 bytes/sample ÷ 22050 Hz)
```

---

## Module Map

```
src/tts/
├── main.py              TTSService orchestrator + async entry point
├── tts_queue.py         TranscriptListener — MongoDB Change Stream
├── synthesizer.py       ElevenLabsSynthesizer — httpx streaming
├── audio_player.py      AudioPlayer — sounddevice OutputStream
├── interrupt_handler.py InterruptHandler — NATS subscriber
├── status_updater.py    TranscriptUpdater — GridFS + doc update
├── config.py            Config dataclass — env var loading
├── logging_config.py    JSON structured logging setup
└── exceptions.py        ElevenLabs typed exception hierarchy

models/
└── tts_queue.py         Pydantic schemas: TTSQueueDocument, TranscriptDocument
```
