# 08 — Integration Guide

This document explains how the TTS service fits into the full meeting bot system and what each surrounding component must do to integrate correctly.

---

## Full System Integration Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    PRODUCTION DEPLOYMENT (Linux)                  │
│                                                                    │
│  ┌─────────────────┐    ┌──────────────────┐    ┌─────────────┐   │
│  │   AI Pipeline   │    │   TTS Service    │    │  PulseAudio │   │
│  │                 │    │                  │    │  virtual_mic│   │
│  │  LLM response   │───▶│  ElevenLabs      │───▶│  (Linux     │   │
│  │  → MongoDB      │    │  synthesis       │    │   sink)     │   │
│  │    insert       │    │                  │    └──────┬──────┘   │
│  └─────────────────┘    └──────────────────┘           │audio     │
│                                                         │          │
│  ┌─────────────────┐    ┌──────────────────┐           │          │
│  │   STT Service   │    │  Headless Browser│◀──────────┘          │
│  │                 │◀───│  (Playwright /   │  reads virtual_mic    │
│  │  transcribes    │    │   Puppeteer)     │  as microphone        │
│  │  candidate      │    │                  │                       │
│  │  speech         │    │  Bot joined the  │───▶ Meeting Platform  │
│  └────────┬────────┘    │  meeting         │     (Zoom/Meet/Teams) │
│           │             └──────────────────┘                       │
│           ▼                                                         │
│  ┌─────────────────┐                                               │
│  │   AI Pipeline   │                                               │
│  │                 │                                               │
│  │  candidate text │                                               │
│  │  → LLM call     │                                               │
│  │  → agent reply  │                                               │
│  └─────────────────┘                                               │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   SHARED INFRASTRUCTURE                      │   │
│  │  MongoDB (replica set) │ NATS (pub/sub) │ Docker network    │   │
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

### 1. AI Pipeline (upstream of TTS)

**What it must do:**

```javascript
// After generating an agent response, write to MongoDB:
db.transcripts.insertOne({
  interview_id: "interview_abc123",  // session identifier
  speaker: "agent",                  // MUST be "agent"
  text: "The agent's response text", // non-empty string
  audio_url: null,                   // MUST be null to trigger TTS
  timestamp: new Date()
})
```

**What it optionally does:**

If the AI pipeline detects user speech starting (barge-in), publish to NATS:
```javascript
nats.publish("tts.interrupt", JSON.stringify({ session_id: "interview_abc123" }))
```

This stops TTS synthesis within 50ms.

**What it must NOT do:**
- Set `audio_url` to anything other than `null` on insert — the TTS service watches for `audio_url: null`
- Insert with `speaker: "candidate"` — the Change Stream filter ignores these

---

### 2. TTS Service (this service)

- Watches MongoDB Change Stream for `speaker: "agent"` + `audio_url: null`
- Calls ElevenLabs API, streams audio to PulseAudio virtual mic
- Stores audio in GridFS, sets `audio_url` to GridFS file ID
- Listens for NATS interrupt to stop mid-synthesis

The AI pipeline can check `audio_url` to know when synthesis is complete.

---

### 3. PulseAudio Virtual Microphone (Linux)

The virtual mic is a PulseAudio null sink. It receives audio from the TTS service via sounddevice and makes it available as an audio source that applications (like the headless browser) can read from.

#### Setup on Linux

```bash
# Load virtual sink
pactl load-module module-null-sink \
  sink_name=virtual_mic \
  sink_properties=device.description=virtual_mic

# Create a monitor source (lets other apps read from virtual_mic as a mic)
pactl load-module module-remap-source \
  master=virtual_mic.monitor \
  source_name=virtual_mic_source

# Verify
pactl list sources short
# Should show: virtual_mic.monitor
```

#### Setup in Docker

The `docker-compose.yml` uses `ghcr.io/mviereck/x11docker/x11docker-pulseaudio` which includes a pre-configured PulseAudio server. The `pulse_socket` volume shares the Unix socket between the PulseAudio container and the TTS container.

```yaml
volumes:
  - pulse_socket:/run/pulse     # shared between pulseaudio + tts containers
```

In the TTS container:
```env
PULSE_SERVER=unix:/run/pulse/native
VIRTUAL_MIC=virtual_mic
```

#### Making Headless Browser Use Virtual Mic

**Playwright (Python)**:
```python
import subprocess
from playwright.async_api import async_playwright

# Set PULSE_SERVER so browser uses the same PulseAudio instance
env = {
    "PULSE_SERVER": "unix:/run/pulse/native",
    "DISPLAY": ":99"  # if using Xvfb
}

async with async_playwright() as p:
    browser = await p.chromium.launch(
        args=[
            "--use-fake-ui-for-media-stream",
            "--alsa-input-device=pulse",
            "--alsa-output-device=pulse",
        ],
        env=env
    )
```

**Puppeteer (Node.js)**:
```javascript
const browser = await puppeteer.launch({
  args: [
    "--use-fake-ui-for-media-stream",
    "--alsa-input-device=pulse",
    "--alsa-output-device=pulse",
  ],
  env: {
    ...process.env,
    PULSE_SERVER: "unix:/run/pulse/native",
  }
});
```

**Joining a meeting with the virtual mic as input**:

The browser's media stream will use the virtual mic as input. When your TTS service writes audio to `virtual_mic`, that audio appears in the browser's media stream and is transmitted to the meeting as the bot's microphone.

---

### 4. STT Service (downstream of meeting)

The headless browser receives audio from meeting participants. This audio needs to be transcribed to text for the AI pipeline to process.

**Integration point**: The STT service reads audio from the meeting (via browser `getUserMedia` or screen capture) and writes transcripts to MongoDB:

```javascript
db.transcripts.insertOne({
  interview_id: "interview_abc123",
  speaker: "candidate",             // "candidate", not "agent"
  text: "The candidate's response",
  audio_url: "played",              // not null — so TTS ignores it
  timestamp: new Date()
})
```

Using `audio_url: "played"` (not `null`) ensures the TTS service Change Stream filter ignores these documents.

---

## End-to-End Flow — One Conversation Turn with Interrupt

```
AI Pipeline        MongoDB         TTS Service       NATS        Audio
    │                 │                │               │            │
    │── insertOne ───▶│                │               │            │
    │  (speaker:agent,│                │               │            │
    │   audio_url:null│                │               │            │
    │                 │──changeEvent──▶│               │            │
    │                 │                │──ElevenLabs──▶            │
    │                 │                │◀──PCM chunks──            │
    │                 │                │                    play───▶│
    │                 │                │                            │
    │ [candidate starts speaking]      │               │            │
    │── tts.interrupt ────────────────────────────────▶│            │
    │                 │                │◀─stop_event───│            │
    │                 │                │                    stop───▶│
    │                 │◀──audio_url────│               │            │
```

---

## Network Requirements

| From | To | Port | Protocol |
|---|---|---|---|
| TTS Service | MongoDB | 27017 | TCP |
| TTS Service | NATS | 4222 | TCP |
| TTS Service | ElevenLabs API | 443 | HTTPS |
| TTS Service | PulseAudio | Unix socket | IPC |
| AI Pipeline | MongoDB | 27017 | TCP |
| AI Pipeline | NATS | 4222 | TCP |
| Headless Browser | Meeting Platform | 443 | HTTPS/WebRTC |

In Docker Compose, all services share the default bridge network and address each other by service name (`mongodb`, `nats`, `pulseaudio`).
