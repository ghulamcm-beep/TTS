# TTS Service Constitution

## Core Principles

### I. Streaming-First
All audio synthesis and playback must be streaming. No blocking file-based operations. Stream text → stream audio chunks → immediate playback.

### II. Interruptible (<50ms)
TTS playback must stop within 50ms of receiving interrupt signal. User experience is paramount - candidate interruption feels instant.

### III. sounddevice for Audio
Use sounddevice OutputStream for audio playback. Enables streaming, interrupt control, and low-latency PulseAudio integration.

### IV. NATS for Real-Time Control
Use NATS Pub/Sub for interruption signals and real-time coordination. MongoDB for persistence, NATS for control.

### V. Piper TTS Engine
Use Piper TTS for offline neural speech synthesis. No external API dependencies. Self-contained, production-ready.

### VI. PulseAudio Virtual Mic
Output audio to PulseAudio virtual_mic device. Browser captures this as microphone input for meeting injection.

### VII. MongoDB Change Streams
Use MongoDB Change Streams for TTS queue processing. Persistent, reliable, auditable task queue.

### VIII. Test-First (NON-NEGOTIABLE)
TDD mandatory: Tests written → Tests fail → Then implement. Red-Green-Refactor cycle strictly enforced.

### IX. Simplicity (YAGNI)
Start simple. No over-engineering. Add complexity only when proven necessary.

## Technology Stack

- **Language**: Python 3.11+
- **TTS Engine**: Piper TTS (piper-tts pip package)
- **Audio Output**: sounddevice (PortAudio wrapper)
- **Event Bus**: NATS (pub/sub for control signals)
- **Queue**: MongoDB (tts_queue collection, change streams)
- **Audio Format**: PCM 16-bit, 22050Hz, mono, s16le
- **Target Platform**: Docker containers (Linux)

## Performance Goals

- **First audio latency**: 100-200ms from text received
- **Interruption latency**: <50ms from NATS signal to audio stop
- **Audio quality**: 22050Hz sample rate, 16-bit
- **Concurrent utterances**: 1 (single speaker, interruptible)

## Development Workflow

- All features start with spec.md
- Plan before implementation
- Tasks tracked in tasks.md
- Commits reference task IDs
- PRs require passing tests

## Quality Gates

- All tests must pass before merge
- No unresolved placeholders in docs
- Interruption latency verified in integration tests
- Docker build succeeds

**Version**: 1.0.0 | **Ratified**: 2026-02-20 | **Last Amended**: 2026-02-20
