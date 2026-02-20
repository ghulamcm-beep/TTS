# Feature Specification: TTS Service (Text-to-Speech)

**Feature Branch**: `001-tts-service`
**Created**: 2026-02-20
**Status**: Draft
**Input**: Standalone TTS service with Piper TTS, NATS for interruption, MongoDB for queue, sounddevice for audio output

## User Scenarios & Testing

### User Story 1 - TTS Queue Processing (Priority: P1)

**Description**: TTS service listens to MongoDB `tts_queue` collection for new text-to-speech tasks. When a new document is inserted, the service synthesizes speech using Piper TTS and plays it through PulseAudio virtual microphone.

**Why this priority**: Core functionality - without queue processing, there is no TTS service. This is the MVP.

**Independent Test**: Insert a document into `tts_queue` → Audio plays through virtual_mic → Status updates to `completed`.

**Acceptance Scenarios**:

1. **Given** TTS service is running, **When** new document inserted into `tts_queue`, **Then** audio synthesis starts within 500ms
2. **Given** text is valid, **When** Piper synthesizes, **Then** audio plays through virtual_mic
3. **Given** synthesis completes, **When** playback finishes, **Then** MongoDB status updates to `completed`

---

### User Story 2 - Interruption via NATS (Priority: P1)

**Description**: TTS service subscribes to NATS channel `tts.interrupt`. When interrupt signal received, immediately stops audio playback within 50ms.

**Why this priority**: Critical for conversational AI - candidate interruption must feel instant. Without this, user experience is broken.

**Independent Test**: TTS is speaking → Publish interrupt to NATS → Audio stops within 50ms.

**Acceptance Scenarios**:

1. **Given** TTS is playing audio, **When** NATS `tts.interrupt` received, **Then** audio stops within 50ms
2. **Given** interrupt received, **When** audio stops, **Then** MongoDB status updates to `interrupted`
3. **Given** audio stopped, **When** new queue item arrives, **Then** TTS can speak again (no deadlock)

---

### User Story 3 - Status Updates to MongoDB (Priority: P2)

**Description**: TTS service updates MongoDB document status throughout lifecycle: `pending` → `playing` → `completed` or `interrupted`. Includes timestamps for observability.

**Why this priority**: Enables other services (Brain, Control, STT) to track TTS state. Required for state machine coordination.

**Independent Test**: Query MongoDB document → Observe status transitions and timestamps.

**Acceptance Scenarios**:

1. **Given** new queue item with status `pending`, **When** TTS starts synthesis, **Then** status updates to `playing` with `started_at` timestamp
2. **Given** playback completes normally, **When** done, **Then** status updates to `completed` with `completed_at` timestamp
3. **Given** playback interrupted, **When** stop completes, **Then** status updates to `interrupted` with `interrupted_at` timestamp

---

### User Story 4 - Piper Model Management (Priority: P2)

**Description**: TTS service manages Piper TTS subprocess lifecycle. Auto-starts Piper on first request, auto-restarts if it crashes, handles model loading timeouts.

**Why this priority**: Piper is external subprocess - must be robust against crashes, timeouts, and resource constraints.

**Independent Test**: Kill Piper subprocess → Service detects and restarts → Next synthesis succeeds.

**Acceptance Scenarios**:

1. **Given** Piper not running, **When** synthesis requested, **Then** Piper starts automatically
2. **Given** Piper crashes mid-synthesis, **When** error detected, **Then** Piper restarts and retry succeeds
3. **Given** high load, **When** multiple requests arrive, **Then** Piper handles sequentially (no concurrent synthesis)

---

### User Story 5 - Error Handling & Recovery (Priority: P3)

**Description**: TTS service handles errors gracefully: MongoDB connection loss, NATS disconnection, PulseAudio device unavailable, Piper failures. Logs errors and attempts recovery.

**Why this priority**: Production reliability - service must recover from transient failures without manual intervention.

**Independent Test**: Simulate failures (kill MongoDB, disconnect NATS, etc.) → Service logs error → Recovers when service restored.

**Acceptance Scenarios**:

1. **Given** MongoDB unavailable, **When** connection restored, **Then** change stream resumes automatically
2. **Given** NATS disconnected, **When** reconnected, **Then** interrupt subscription resumes
3. **Given** PulseAudio device unavailable, **When** error occurs, **Then** error logged and status updated to `failed`

---

## Requirements

### Functional Requirements

- **FR-001**: System MUST subscribe to MongoDB `tts_queue` collection via Change Streams
- **FR-002**: System MUST synthesize text using Piper TTS subprocess
- **FR-003**: System MUST play audio via sounddevice OutputStream to PulseAudio virtual_mic
- **FR-004**: System MUST subscribe to NATS `tts.interrupt` channel for stop signals
- **FR-005**: System MUST stop audio playback within 50ms of interrupt signal
- **FR-006**: System MUST update MongoDB document status: `pending` → `playing` → `completed`/`interrupted`/`failed`
- **FR-007**: System MUST auto-start Piper TTS subprocess on first synthesis request
- **FR-008**: System MUST auto-restart Piper if it crashes during synthesis
- **FR-009**: System MUST handle one utterance at a time (no concurrent playback)
- **FR-010**: System MUST log all status transitions and errors with timestamps

### Key Entities

- **TTSQueue**: MongoDB document representing a TTS task. Fields: `_id`, `session_id`, `text`, `status`, `priority`, `created_at`, `started_at`, `completed_at`, `interrupted_at`, `error_message`
- **InterruptSignal**: NATS message triggering immediate stop. Payload: `session_id` (optional, for targeted interruption)
- **PiperProcess**: Managed subprocess running Piper TTS. Handles stdin (text) → stdout (PCM audio chunks)

## Success Criteria

### Measurable Outcomes

- **SC-001**: First audio plays within 200ms of MongoDB insert (measured from `created_at` to first chunk written)
- **SC-002**: Interruption latency <50ms (measured from NATS publish to sounddevice.stop())
- **SC-003**: 99% successful synthesis rate (completed / total attempts)
- **SC-004**: Zero manual restarts required in 24-hour period (auto-recovery verified)
- **SC-005**: Audio quality: 22050Hz sample rate, 16-bit, mono (verified in tests)
