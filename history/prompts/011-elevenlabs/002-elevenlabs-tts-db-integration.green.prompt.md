---
id: 002
title: ElevenLabs TTS + interviews DB Integration
stage: green
date: 2026-02-23
surface: agent
model: claude-sonnet-4-6
feature: 011-elevenlabs
branch: 11
user: parep
command: implement plan
labels: ["elevenlabs","tts","mongodb","httpx","interviews","transcripts"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - pyproject.toml
  - .env.example
  - src/tts/config.py
  - src/tts/synthesizer.py
  - src/tts/exceptions.py
  - src/tts/tts_queue.py
  - src/tts/status_updater.py
  - src/tts/main.py
  - models/tts_queue.py
  - tests/unit/test_synthesizer.py
  - tests/unit/test_status_updater.py
tests:
  - tests/unit/test_synthesizer.py (9 tests — all pass)
  - tests/unit/test_status_updater.py (3 tests — all pass)
  - tests/unit/test_interrupt_handler.py (6 tests — all pass, unchanged)
---

## Prompt

Implement the following plan:

# Plan: ElevenLabs TTS + interviews DB Integration

Replace Piper TTS with ElevenLabs and fix the MongoDB collection mismatch: watch `interviews.transcripts` (where main-agent writes) instead of `tts_service.tts_queue` (which nobody writes to). Make NATS optional so the service runs without a NATS server.

## Response snapshot

Implemented all 9 file changes from the plan:

1. **pyproject.toml** — Added `httpx>=0.27.0` dependency
2. **.env.example** — Added ElevenLabs vars, changed DB to `interviews`, made NATS optional
3. **config.py** — Added ElevenLabs config fields, changed default DB to `interviews`, added `transcripts_collection`, removed Piper fields, made `nats_uri` default empty
4. **models/tts_queue.py** — Added `TranscriptDocument` model for `interviews.transcripts` schema
5. **src/tts/exceptions.py** (new) — Custom exception hierarchy: `ElevenLabsError`, `ElevenLabsAuthError`, `ElevenLabsRateLimitError`, `ElevenLabsServerError`, `ElevenLabsNetworkError`
6. **src/tts/synthesizer.py** — Full rewrite: `ElevenLabsSynthesizer` using `httpx.AsyncClient` for streaming PCM from ElevenLabs API
7. **src/tts/tts_queue.py** — Renamed to `TranscriptListener`, watches `interviews.transcripts` with pipeline filter for `speaker=agent, audio_url=null`
8. **src/tts/status_updater.py** — Renamed to `TranscriptUpdater`, writes `audio_url="played"` on completion
9. **src/tts/main.py** — Updated all imports, made NATS connection optional with graceful fallback, updated task flow for `TranscriptDocument`
10. **tests/unit/test_synthesizer.py** — Full rewrite for `ElevenLabsSynthesizer` (9 tests)
11. **tests/unit/test_status_updater.py** — Full rewrite for `TranscriptUpdater` (3 tests)

All 19 unit tests pass.

## Outcome

- ✅ Impact: ElevenLabs replaces Piper; service now watches the correct collection (`interviews.transcripts`); NATS is optional; handoff signal is `audio_url="played"`
- 🧪 Tests: 19/19 unit tests pass (pytest tests/unit/ -v)
- 📁 Files: 11 files created/modified
- 🔁 Next prompts: Add `.env` with real API key and test end-to-end with mongosh insert; consider integration test suite update
- 🧠 Reflection: httpx streaming approach via `aiter_bytes()` maps cleanly to the existing `AudioPlayer.play()` interface which already accepts an async generator

## Evaluation notes (flywheel)

- Failure modes observed: none — all tests passed first run
- Graders run and results (PASS/FAIL): pytest tests/unit/ → 19 PASS
- Prompt variant (if applicable): null
- Next experiment: end-to-end test with real ElevenLabs API key and MongoDB replica set
