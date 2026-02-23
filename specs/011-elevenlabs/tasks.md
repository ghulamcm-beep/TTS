# Tasks: ElevenLabs TTS Synthesizer

**Input**: Design documents from `specs/011-elevenlabs/`
**Prerequisites**: spec.md (required), plan.md (required), research.md (required)
**Tests**: TDD mandatory — write tests first, then implement
**Scope**: Replace synthesizer only. All other modules unchanged.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: Install dependencies, update configuration

- [ ] T001 Add `httpx>=0.27.0` to pyproject.toml and requirements.txt via `uv add httpx`
- [ ] T002 [P] Extend `src/tts/config.py` with ElevenLabs settings (API key, voice ID, model ID, output format, base URL, timeouts, retry config)
- [ ] T003 [P] Add `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID` to `.env.example`

---

## Phase 2: Tests First (Red Phase)

**Purpose**: Write all tests before implementation — verify they fail

**⚠️ CRITICAL**: Run tests after writing each — confirm they FAIL before implementing

### Contract Tests

- [ ] T004 [P] [US1] Create `tests/contract/test_elevenlabs_contract.py`:
  - Verify config has `elevenlabs_api_key`, `elevenlabs_voice_id`, `elevenlabs_model_id`
  - Verify output format is `pcm_22050`
  - Verify base URL format is correct
  - Verify `xi-api-key` header name constant

### Unit Tests

- [ ] T005 [P] [US1] Create `tests/unit/test_synthesizer.py` (replaces existing Piper tests):
  - `test_synthesize_yields_pcm_chunks` — mock httpx 200, verify bytes yielded
  - `test_synthesize_retry_on_429` — mock 429 then 200, verify retry logic
  - `test_synthesize_raises_on_401` — mock 401, verify raises immediately
  - `test_synthesize_raises_on_403` — mock 403 (quota), verify raises
  - `test_synthesize_stop_event_exits_cleanly` — set stop_event mid-stream, verify no exception
  - `test_synthesize_timeout_raises` — mock read timeout, verify raises
  - `test_close_cancels_request` — verify close() sets internal cancel flag

- [ ] T006 [P] [US2] Create `tests/unit/test_synthesizer_interrupt.py`:
  - `test_stop_event_checked_between_chunks` — stop_event set after 2 chunks, verify stream exits after 2
  - `test_http_connection_closed_on_interrupt` — verify httpx client closed when stop_event fires

### Integration Tests

- [ ] T007 [P] [US1] Create `tests/integration/test_elevenlabs_flow.py`:
  - `test_full_pipeline_text_to_chunks` — mock httpx, verify chunks flow through synthesizer to fake player
  - `test_status_updated_on_success` — full mock pipeline, verify status=completed

- [ ] T008 [P] [US3] Update `tests/integration/test_error_recovery.py`:
  - `test_quota_exceeded_sets_failed_status` — mock 403, verify status=failed + error_message
  - `test_rate_limit_retries_then_fails` — mock 429 × 3, verify retries exhausted → status=failed
  - `test_api_key_missing_raises_on_startup` — empty API key → validate error

---

## Phase 3: Implementation (Green Phase)

**Purpose**: Make tests pass. Smallest viable implementation.

- [ ] T009 [US1] Rewrite `src/tts/synthesizer.py` as `ElevenLabsSynthesizer`:
  - Class with `synthesize(text, stop_event) -> AsyncGenerator[bytes, None]`
  - Uses `httpx.AsyncClient` with `async with client.stream(...)` pattern
  - Sets headers: `{"xi-api-key": config.elevenlabs_api_key, "Content-Type": "application/json"}`
  - Sets params: `{"output_format": config.elevenlabs_output_format}`
  - Body: `{"text": text, "model_id": config.elevenlabs_model_id, "voice_settings": {...}}`
  - Yields `chunk` from `response.aiter_bytes(chunk_size=config.chunk_size)`
  - Checks `stop_event.is_set()` between each chunk — returns early if set
  - Raises `ElevenLabsAuthError` on 401
  - Raises `ElevenLabsQuotaError` on 403
  - Raises `ElevenLabsValidationError` on 422
  - Retries on 429 with `asyncio.sleep(delay * 2^attempt)`, max `config.elevenlabs_max_retries`
  - `close()` method: sets internal `_cancelled` flag

- [ ] T010 [US1] Add custom exceptions to `src/tts/synthesizer.py`:
  - `ElevenLabsError(Exception)` — base
  - `ElevenLabsAuthError(ElevenLabsError)` — 401
  - `ElevenLabsQuotaError(ElevenLabsError)` — 403
  - `ElevenLabsValidationError(ElevenLabsError)` — 422
  - `ElevenLabsRateLimitError(ElevenLabsError)` — 429 retries exhausted

- [ ] T011 [US3] Update `src/tts/main.py` `_process_task` to catch `ElevenLabsAuthError` / `ElevenLabsQuotaError` separately:
  - On `ElevenLabsQuotaError`: set status=failed with clear message, log warning (don't crash service)
  - On `ElevenLabsAuthError`: log critical + stop service (misconfiguration, no point continuing)

---

## Phase 4: Validation

**Purpose**: Run all tests, verify green

- [ ] T012 Run `uv run pytest tests/ -v` — all tests must pass
- [ ] T013 [P] Verify no real HTTP calls made in tests (no `elevenlabs.io` hits)
- [ ] T014 [P] Check `ELEVENLABS_API_KEY` is never logged (grep for api_key in logs)

---

## Phase 5: Polish

- [ ] T015 [P] Update `README.md` with ElevenLabs setup section (API key, voice config, free tier note)
- [ ] T016 [P] Update `Dockerfile` — remove piper/PulseAudio compile deps if no longer needed
- [ ] T017 [P] Update `docker-compose.yml` — add `ELEVENLABS_API_KEY` env pass-through
- [ ] T018 [P] Update `specs/011-elevenlabs/tasks.md` — mark completed tasks [X]

---

## Dependencies & Execution Order

```
T001 → T002, T003 (config before tests)
T004-T008 (tests, parallel — all fail initially)
T009 → T010 → T011 (implementation sequential)
T012-T014 (validation)
T015-T018 (polish, parallel)
```

### TDD Checkpoints

1. After T004-T008: confirm `pytest` shows N failures (red)
2. After T009: synthesizer core tests green
3. After T010: exception tests green
4. After T011: integration tests green
5. After T012: all 40+ tests green

---

## Notes

- API key goes in `.env` (gitignored) — never committed
- Tests use `respx` or `unittest.mock` to mock httpx — no real API calls
- Free tier: 20k credits/month on flash model = ~40k chars. Keep test texts under 50 chars.
- Voice ID Rachel = `21m00Tcm4TlvDq8ikWAM` (default, free tier)
- For manual testing: run with real key, use short texts ("Hello world"), check ElevenLabs dashboard for credit usage
- `main.py` calls `synthesizer.synthesize(text)` — signature unchanged ✅
- `audio_player.py` receives PCM chunks — unchanged ✅
- interrupt_handler stop_event passed to synthesize — add `stop_event` param to `synthesize()` signature
