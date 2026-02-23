# Feature Specification: ElevenLabs TTS Synthesizer

**Feature Branch**: `11`
**Feature Dir**: `specs/011-elevenlabs/`
**Created**: 2026-02-20
**Status**: Draft
**Language Scope**: English only
**Input**: Replace Piper TTS subprocess with ElevenLabs streaming API. All other components (MongoDB, NATS, sounddevice, Docker) remain unchanged.

---

## Context

The existing TTS service uses Piper TTS (local subprocess). This feature replaces **only the synthesizer** with ElevenLabs API while keeping the full pipeline intact:

```
MongoDB → [tts_queue.py] → [synthesizer.py ← CHANGE THIS] → [audio_player.py] → PulseAudio
                                                                      ↑
NATS → [interrupt_handler.py] ─────────────────────────────────── stop_event
```

---

## User Stories

### User Story 1 - ElevenLabs Voice Synthesis (Priority: P1) 🎯 MVP

**Description**: When a TTS task is dequeued from MongoDB, the service calls ElevenLabs streaming API with `eleven_flash_v2_5` and `pcm_22050` format, streams audio chunks, and plays them through sounddevice in real-time.

**Why this priority**: Core replacement — without this nothing works.

**Independent Test**: Insert document into `tts_queue` → ElevenLabs synthesizes → Audio plays through virtual_mic → Status updates to `completed`.

**Acceptance Scenarios**:

1. **Given** valid API key + text, **When** synthesis requested, **Then** first audio chunk received within 300ms
2. **Given** audio streaming, **When** chunks arrive, **Then** each chunk is valid PCM (22050Hz, int16, mono)
3. **Given** synthesis complete, **When** stream ends, **Then** MongoDB status updates to `completed`

---

### User Story 2 - Stream Interruption (Priority: P1)

**Description**: When NATS interrupt signal received during ElevenLabs streaming, the HTTP connection closes immediately, audio stops, and status updates to `interrupted`.

**Why this priority**: Core requirement for conversational AI — same as Piper version, must work identically.

**Independent Test**: TTS streaming → Publish NATS interrupt → HTTP stream closes → Audio stops within 50ms → Status = `interrupted`.

**Acceptance Scenarios**:

1. **Given** ElevenLabs streaming in progress, **When** `tts.interrupt` received on NATS, **Then** HTTP stream connection closed within one chunk cycle
2. **Given** stream cancelled, **When** sounddevice buffer drains, **Then** audio silence within 50ms
3. **Given** interrupt during synthesis, **When** done, **Then** MongoDB status = `interrupted`

---

### User Story 3 - Error Handling & Free Tier Awareness (Priority: P1)

**Description**: Service handles ElevenLabs API errors gracefully: rate limiting (429), quota exceeded (403), auth failure (401), network timeouts. Sets document status to `failed` with error message.

**Why this priority**: Free tier has hard limits. Service must not crash or loop on API errors.

**Independent Test**: Simulate API errors → Service logs error → Status updates to `failed` → Service continues watching queue.

**Acceptance Scenarios**:

1. **Given** API key invalid (401), **When** service starts, **Then** service logs error and halts startup
2. **Given** quota exceeded (403), **When** synthesis requested, **Then** status=`failed`, error_message set, service continues
3. **Given** rate limited (429), **When** synthesis requested, **Then** retry up to 3 times with backoff, then fail gracefully
4. **Given** network timeout, **When** first chunk not received in 10s, **Then** status=`failed`, synthesizer resets

---

### User Story 4 - Voice & Model Configuration (Priority: P2)

**Description**: Voice ID, model, and audio format configurable via environment variables. Defaults to Rachel voice + `eleven_flash_v2_5` + `pcm_22050`.

**Acceptance Scenarios**:

1. **Given** `ELEVENLABS_VOICE_ID` env set, **When** service starts, **Then** uses specified voice
2. **Given** `ELEVENLABS_MODEL_ID` env set, **When** synthesis called, **Then** uses specified model
3. **Given** no env vars, **When** service starts, **Then** defaults applied (Rachel, flash_v2_5, pcm_22050)

---

## Requirements

### Functional Requirements

- **FR-001**: System MUST call ElevenLabs `POST /v1/text-to-speech/{voice_id}/stream` for synthesis
- **FR-002**: System MUST use `output_format=pcm_22050` (raw PCM, no decoding needed)
- **FR-003**: System MUST use `eleven_flash_v2_5` model by default (lowest latency, English+)
- **FR-004**: System MUST stream audio chunks directly to sounddevice (no full buffering)
- **FR-005**: System MUST cancel HTTP stream when `stop_event` is set
- **FR-006**: System MUST retry on HTTP 429 with exponential backoff (max 3 retries)
- **FR-007**: System MUST set status=`failed` on unrecoverable errors (401, 403, 422)
- **FR-008**: System MUST authenticate via `xi-api-key` header from `ELEVENLABS_API_KEY` env var
- **FR-009**: System MUST NOT buffer entire audio — stream chunk-by-chunk to maintain <50ms interrupt latency
- **FR-010**: System MUST log all API errors with HTTP status code and response body

### Non-Functional Requirements

- **NFR-001**: First audio chunk within 300ms of synthesis start (network-dependent)
- **NFR-002**: Interruption latency <50ms (stop_event check + sounddevice.stop())
- **NFR-003**: No memory accumulation — chunks processed and discarded, not stored
- **NFR-004**: API key never logged or exposed in error messages
- **NFR-005**: Tests must not make real API calls (mock httpx)

### Out of Scope

- Non-English voices / multilingual support (future feature)
- WebSocket TTS (using HTTP streaming is sufficient for this use case)
- Voice cloning or custom voice creation
- Paid tier features (STS, high concurrency)
- Prometheus metrics (deferred)

---

## Key Entities

- **ElevenLabsSynthesizer**: Replaces `PiperSynthesizer`. Manages httpx async HTTP streaming to ElevenLabs API. Handles retries, auth, cancellation.
- **TTSQueueDocument**: Unchanged — same MongoDB schema
- **InterruptSignal**: Unchanged — same NATS `tts.interrupt` subject
- **Config**: Extended with `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`

---

## Success Criteria

- **SC-001**: First audio within 300ms of MongoDB insert (latency budget: API 75ms + network 80ms + queue 10ms + sounddevice 1ms)
- **SC-002**: Interruption latency <50ms (same as Piper spec)
- **SC-003**: Zero crashes on API errors — all errors caught, logged, status updated
- **SC-004**: 40+ tests pass (keep all existing tests + new ElevenLabs-specific tests)
- **SC-005**: Free tier (20k credits/month) used efficiently — no wasted API calls on retries
