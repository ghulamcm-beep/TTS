# 01 — System Overview

## What This Service Is

The **TTS Service** is a real-time, streaming Text-to-Speech microservice designed as one component of a conversational AI meeting bot. It synthesises agent speech using the ElevenLabs API and outputs raw audio to a PulseAudio virtual microphone, which a headless browser captures and streams into a live meeting as the bot's voice.

---

## The Bigger Picture — Meeting Bot Architecture

This service does not run in isolation. It is one piece of a larger system:

```
┌─────────────────────────────────────────────────────────────────┐
│                    MEETING PLATFORM                             │
│              (Zoom / Google Meet / Teams)                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ hears bot voice via mic
┌──────────────────────────▼──────────────────────────────────────┐
│                 HEADLESS BROWSER (Playwright/Puppeteer)         │
│          Bot joined the meeting, virtual mic as input           │
└──────────┬─────────────────────────────────┬────────────────────┘
           │ captures audio                  │ receives transcript
           │                                 │
┌──────────▼──────────┐          ┌───────────▼────────────────────┐
│   PULSEAUDIO        │          │   SPEECH-TO-TEXT (STT)         │
│   virtual_mic sink  │          │   Transcribes candidate audio  │
└──────────▲──────────┘          └───────────┬────────────────────┘
           │ audio output                     │ transcript
           │                                 │
┌──────────┴──────────┐          ┌───────────▼────────────────────┐
│  ◀ THIS SERVICE ▶   │◀─────────│   AI RESPONSE PIPELINE         │
│  TTS Microservice   │ MongoDB  │   LLM generates agent reply    │
│  ElevenLabs + Sound │ insert   └────────────────────────────────┘
└─────────────────────┘
```

### Role of Each Component

| Component | Responsibility |
|---|---|
| **Meeting Platform** | Hosts the video call; receives audio from the bot's mic |
| **Headless Browser** | Joins the meeting programmatically; relays virtual mic audio as mic input |
| **PulseAudio virtual_mic** | Linux virtual audio sink; TTS writes here, browser reads here |
| **STT Service** | Transcribes candidate/user speech to text |
| **AI Pipeline** | LLM processes transcripts and generates agent responses |
| **MongoDB** | Shared state between AI pipeline and TTS; source of synthesis requests |
| **THIS SERVICE** | Receives text from MongoDB, synthesises with ElevenLabs, plays to virtual mic |

---

## What This Service Does — Step by Step

1. **Watches MongoDB** for new documents in `interviews.transcripts` where `speaker = "agent"` and `audio_url = null` (meaning: new agent utterance, not yet synthesised)
2. **Calls ElevenLabs** streaming API with the text; receives raw PCM audio chunks
3. **Streams chunks** directly to the sounddevice output (PulseAudio virtual mic in production, real speakers locally)
4. **Stores audio** in MongoDB GridFS for caching and audit
5. **Handles interrupts** via NATS — if a new user utterance starts mid-speech, synthesis stops within 50ms

---

## What Problems It Solves

| Problem | Solution |
|---|---|
| Agent must respond in real-time during a live call | ElevenLabs streaming: first audio in <300ms |
| Agent must stop speaking when user starts | NATS interrupt + asyncio.Event: <50ms stop latency |
| Audio must reach the meeting without a real microphone | PulseAudio virtual sink → headless browser reads it as a mic |
| Synthesis requests must survive service restarts | MongoDB Change Streams: persistent queue, no messages lost |
| Repeated phrases should not re-hit the API | GridFS audio cache: plays stored PCM on cache hit |

---

## Standalone Testing Mode

During development and local testing, the headless browser and meeting platform are absent. The service is run directly:

- MongoDB runs locally (replica set required for Change Streams)
- Audio plays to a real speaker/headphone (Windows: device ID; Linux: PulseAudio)
- NATS is optional (interrupt feature disabled when `NATS_URI` is empty)
- Synthesis can be triggered by inserting documents directly into MongoDB

This is the mode described in the rest of these docs unless otherwise noted.
