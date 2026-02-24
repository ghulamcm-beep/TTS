---
id: 002
title: Fix Failing Tests After ElevenLabs Migration
stage: general
date: 2026-02-24
surface: agent
model: claude-sonnet-4-6
feature: none
branch: 11
user: architext
command: (conversational — "perform the testing")
labels: ["testing","bugfix","elevenlabs","nats"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - tests/integration/test_error_recovery.py
  - tests/contract/test_nats_protocol.py
tests:
  - tests/integration/test_error_recovery.py::TestErrorRecovery::test_synthesizer_stateless_after_error
  - tests/contract/test_nats_protocol.py::TestNATSProtocol::test_nats_uri_format
---

## Prompt

perform the testing

## Response snapshot

Ran full pytest suite (43 tests). Found 2 failures:

1. `test_synthesizer_resets_after_success` — `ImportError: cannot import name 'PiperSynthesizer'`. Stale test from pre-ElevenLabs era; `PiperSynthesizer` was replaced by `ElevenLabsSynthesizer` on branch 11. Fixed by replacing with `test_synthesizer_stateless_after_error`, which verifies `ElevenLabsSynthesizer` carries no failure state between calls.

2. `test_nats_uri_format` — `AssertionError` because `config.nats_uri == ''`. NATS is intentionally optional (config.py comment: "leave NATS_URI empty to disable interrupt feature"). Fixed by adding `pytest.skip` when `nats_uri` is empty.

Final result: **42 passed, 1 skipped, 0 failed**.

## Outcome

- ✅ Impact: All tests passing; stale Piper test replaced with valid ElevenLabs equivalent; NATS optional contract correctly expressed
- 🧪 Tests: 42 passed, 1 skipped (test_nats_uri_format skips when NATS_URI not configured)
- 📁 Files: tests/integration/test_error_recovery.py, tests/contract/test_nats_protocol.py
- 🔁 Next prompts: address Pydantic deprecation warnings (json_encoders, datetime.utcnow) in models/tts_queue.py
- 🧠 Reflection: Both failures were migration artifacts — Piper→ElevenLabs left a stale import, and an optional feature's contract test assumed it was always configured

## Evaluation notes (flywheel)

- Failure modes observed: stale test imports after component replacement; contract test not accounting for optional feature config
- Graders run and results (PASS/FAIL): pytest — PASS (42 passed, 1 skipped)
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): fix datetime.utcnow() deprecation in models/tts_queue.py using datetime.now(UTC)
