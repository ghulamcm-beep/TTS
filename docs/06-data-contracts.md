# 06 — Data Contracts

This document defines every data format that crosses a service boundary: MongoDB documents, GridFS files, and NATS messages. Any system that integrates with the TTS service must conform to these contracts.

---

## MongoDB — `interviews.transcripts`

### Collection Requirements

- Database: `interviews` (configurable via `MONGODB_DB`)
- Collection: `transcripts` (configurable via `TRANSCRIPTS_COLLECTION`)
- MongoDB must be running as a **replica set** (`rs0`) — required for Change Streams

### Document Schema

```javascript
{
  _id: ObjectId | string,         // MongoDB document ID (any type)
  interview_id: string,           // groups utterances by session/interview
  speaker: "agent" | "candidate", // who said it — only "agent" is synthesised
  text: string,                   // the text to synthesise (UTF-8, English)
  audio_url: null | "played" | string(ObjectId),  // synthesis status sentinel
  audio_data: BinData | null,     // (optional) inline PCM bytes — rarely populated
  audio_format: string | null,    // "pcm_22050" when audio_data is set
  timestamp: Date | null          // when the utterance was created
}
```

### Field: `audio_url` — State Machine

The TTS service uses `audio_url` as a state machine field:

```
null
 │  ← insert with audio_url: null triggers Change Stream
 ▼
"played"           (synthesis failed or audio device unavailable)
  OR
"<GridFS ObjectId>" (synthesis succeeded, audio stored in GridFS)
```

**The Change Stream filter**:
```javascript
{ "fullDocument.speaker": "agent", "fullDocument.audio_url": null }
```

Only documents satisfying both conditions trigger synthesis.

### Inserting a Synthesis Request

Minimum required fields:

```javascript
db.transcripts.insertOne({
  interview_id: "interview_001",    // required: string
  speaker: "agent",                 // required: must be "agent"
  text: "Hello, how are you?",      // required: non-empty string
  audio_url: null,                  // required: must be null to trigger synthesis
  timestamp: new Date()             // recommended for ordering
})
```

### After Synthesis

```javascript
// Successful synthesis:
{ audio_url: "683abc...def" }  // GridFS file ObjectId as string

// Failed / no audio device:
{ audio_url: "played" }
```

---

## MongoDB — GridFS `audio` Bucket

Synthesised PCM audio is stored in GridFS under the `audio` bucket. This creates two collections:

- `audio.files` — file metadata
- `audio.chunks` — 255KB binary chunks

### File Naming

```
transcript_{document_id}.pcm
```

Example: `transcript_683abc123.pcm`

### File Metadata

```javascript
// audio.files document
{
  _id: ObjectId,               // this is the value stored in audio_url
  filename: "transcript_683abc123.pcm",
  length: 100352,              // total bytes
  chunkSize: 261120,           // 255KB per chunk
  uploadDate: ISODate,
  metadata: {
    transcript_id: "683abc123",
    format: "pcm_22050",
    sample_rate: 22050,
    channels: 1,
    bits: 16
  }
}
```

### Audio Format

| Property | Value |
|---|---|
| Encoding | Raw PCM (no container, no header) |
| Sample rate | 22050 Hz |
| Bit depth | 16-bit signed integer (little-endian) |
| Channels | 1 (mono) |
| Bytes per second | 22050 × 2 = 44,100 bytes/s |
| Duration formula | `file.length / 44100` seconds |

### Retrieving Audio from GridFS

```python
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from bson import ObjectId

client = AsyncIOMotorClient("mongodb://localhost:27017/?replicaSet=rs0")
db = client["interviews"]
bucket = AsyncIOMotorGridFSBucket(db, bucket_name="audio")

# audio_url from the transcript document
file_id = ObjectId("683abc123def456789012345")
stream = await bucket.open_download_stream(file_id)
pcm_bytes = await stream.read()

# Play with sounddevice
import numpy as np
import sounddevice as sd
audio = np.frombuffer(pcm_bytes, dtype=np.int16)
sd.play(audio, samplerate=22050)
sd.wait()
```

Or use the provided utility script:
```bash
uv run python scripts/play_from_db.py
```

---

## NATS — Interrupt Protocol

### Subject

```
tts.interrupt
```

Configurable via `config.nats_interrupt_subject` (currently hardcoded to `"tts.interrupt"`).

### Message Payload

**Broadcast interrupt** — stops any active synthesis immediately:
```json
{}
```
or empty bytes: `b""`

**Session-targeted interrupt** — (future: currently treated same as broadcast):
```json
{"session_id": "sess_001"}
```

### Publishing an Interrupt

```bash
# Using nats CLI
nats pub tts.interrupt '{}'

# Using Docker exec
docker compose exec nats nats pub tts.interrupt '{}'

# Using Python nats-py
import asyncio
import nats

async def interrupt():
    nc = await nats.connect("nats://localhost:4222")
    await nc.publish("tts.interrupt", b"{}")
    await nc.close()

asyncio.run(interrupt())
```

### Effect

An interrupt message causes:
1. `InterruptHandler._stop_event.set()` immediately
2. `AudioPlayer` exits the chunk loop on the next iteration (≤93ms)
3. The httpx stream connection is abandoned (closed by GC)
4. `TTSService` marks the transcript as interrupted: `audio_url = "played"`

### NATS Server Configuration

The NATS server requires JetStream to be enabled (for potential future use). Start with:
```bash
nats-server -js
```

Or via Docker: `command: ["-js"]` in `docker-compose.yml`.

---

## ElevenLabs API — Synthesis Endpoint

This is the external API the synthesiser calls. Documented here for reference.

```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream
     ?output_format=pcm_22050

Request Headers:
  xi-api-key: {ELEVENLABS_API_KEY}
  Content-Type: application/json

Request Body:
  {
    "text": "The text to synthesise",
    "model_id": "eleven_flash_v2_5"
  }

Response:
  Content-Type: audio/mpeg  (despite being raw PCM — ElevenLabs quirk)
  Body: binary stream of raw signed 16-bit PCM at 22050Hz mono
```

### Rate Limits (Free Tier)

| Limit | Value |
|---|---|
| Characters/month | 10,000 |
| Concurrent requests | 2 |
| Rate limit status | HTTP 429 |

### Error Responses

| Status | Meaning | Service Behaviour |
|---|---|---|
| 200 | Success | Stream PCM chunks |
| 401 | Invalid API key | Raise `ElevenLabsAuthError` |
| 429 | Rate limit / quota | Raise `ElevenLabsRateLimitError` |
| 422 | Invalid parameters | Raise `ElevenLabsError` |
| 5xx | Server error | Raise `ElevenLabsServerError` |

---

## Integration Checklist

If you are building a system that feeds documents into this TTS service, ensure:

- [ ] MongoDB is a replica set (not standalone)
- [ ] Documents are inserted into the correct database and collection (`interviews.transcripts`)
- [ ] `speaker` field is exactly `"agent"` (case-sensitive)
- [ ] `audio_url` field is explicitly `null` (not missing, not `""`)
- [ ] `text` field is a non-empty UTF-8 string
- [ ] `interview_id` is provided (string, used for logging and future grouping)
- [ ] Your system handles the `audio_url` field being set asynchronously (it is set after synthesis, not immediately)
