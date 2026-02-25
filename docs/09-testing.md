# 09 — Testing Guide

---

## Test Structure

```
tests/
├── unit/
│   ├── test_synthesizer.py       ElevenLabsSynthesizer — all mocked, no real API
│   ├── test_interrupt_handler.py InterruptHandler — asyncio.Event behaviour
│   └── test_status_updater.py    TranscriptUpdater — mocked MongoDB + GridFS
├── integration/
│   ├── test_queue_to_audio.py    Document parsing + status transition logic
│   ├── test_interruption_flow.py stop_event propagation end-to-end (mocked)
│   └── test_error_recovery.py    ElevenLabs error recovery, NATS resilience
└── contract/
    ├── test_mongodb_schema.py    TTSQueueDocument Pydantic schema validation
    └── test_nats_protocol.py     NATS subject + message format validation
```

### Test Philosophy

| Layer | What it tests | Infrastructure needed |
|---|---|---|
| Unit | Single class in isolation | None — all mocked |
| Integration | Multiple classes interacting | None — external calls mocked |
| Contract | Data schemas and protocols | None — validates formats only |

No tests require a real MongoDB, NATS, or ElevenLabs connection. All external dependencies are mocked.

---

## Running Tests

### All tests

```bash
uv run pytest tests/ -v
```

Expected result: **42 passed, 1 skipped** (NATS URI format test skips when `NATS_URI` is empty).

### Unit tests only

```bash
uv run pytest tests/unit/ -v
```

### Integration tests only

```bash
uv run pytest tests/integration/ -v
```

### Contract tests only

```bash
uv run pytest tests/contract/ -v
```

### Run a single test

```bash
uv run pytest tests/unit/test_synthesizer.py::TestElevenLabsSynthesizer::test_synthesize_yields_chunks -v
```

### With short tracebacks

```bash
uv run pytest tests/ --tb=short
```

---

## Test Configuration — `pytest.ini`

```ini
[pytest]
asyncio_mode = auto       # all async tests run automatically without @pytest.mark.asyncio
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
log_cli = true            # show log output inline during test run
log_cli_level = INFO
```

`asyncio_mode = auto` means async test functions are automatically treated as asyncio coroutines — no decorator needed at the function level (though `@pytest.mark.asyncio` still works).

---

## What Each Test Covers

| File | What it tests |
|---|---|
| `unit/test_synthesizer.py` | ElevenLabs streaming; 401/429/5xx/timeout error mapping; `_raise_for_status` helper |
| `unit/test_interrupt_handler.py` | `stop_event` set/clear lifecycle; NATS connect/close; empty payload resilience |
| `unit/test_status_updater.py` | GridFS upload; `audio_url` field set correctly; ObjectId and string IDs |
| `integration/test_queue_to_audio.py` | Raw MongoDB dict → `TranscriptDocument`; status transition order |
| `integration/test_interruption_flow.py` | `stop_event` propagates to AudioPlayer; reset between utterances |
| `integration/test_error_recovery.py` | Synthesizer stateless after failure; missing `fullDocument` skipped safely |
| `contract/test_mongodb_schema.py` | `TTSQueueDocument` schema, enums, `_id` alias, timestamps |
| `contract/test_nats_protocol.py` | Subject name, payload formats, NATS URI format (skips if not configured) |

All external calls (httpx, motor, nats) are mocked — no real infrastructure required.

---

## Live Testing — Benchmark Script

Measures real end-to-end latency from MongoDB insert to synthesis complete.

**Requires**: TTS service running (`uv run python -m src.tts.main`)

```bash
# Default text (64 chars)
uv run python scripts/benchmark.py

# Custom text
uv run python scripts/benchmark.py --text "The quick brown fox jumped over the lazy dog"
```

**Output**:
```
[benchmark] Text       : 44 chars
[benchmark] Inserting document...
[benchmark] Inserted   : 699d76f2...  (+28ms)
[benchmark] Waiting for synthesis (timeout=60s)...

[benchmark] ✓ Synthesis complete
[benchmark] ─────────────────────────────
[benchmark]  Insert latency   : 28ms      ← MongoDB round-trip
[benchmark]  Synthesis + save : 1129ms    ← ElevenLabs + GridFS
[benchmark]  Total latency    : 1157ms    ← insert to audio_url set
[benchmark]  Chars/second     : 38.0
[benchmark]  audio_url        : 699d76f3...
```

**Interpretation**:
- `Insert latency` = MongoDB write + Change Stream push (~10–30ms local)
- `Synthesis + save` = ElevenLabs API + audio play + GridFS write
- `Total latency` = wall clock from insert to audio done

Typical values on good network:
| Text length | Total latency |
|---|---|
| 20 chars | ~800ms |
| 50 chars | ~1100ms |
| 100 chars | ~1500ms |
| 200 chars | ~2500ms |

---

## Live Testing — Play from DB

Plays previously synthesised audio from GridFS without calling ElevenLabs.

```bash
# List and play
uv run python scripts/play_from_db.py

# List only (no playback)
uv run python scripts/play_from_db.py --list

# Show all (not just last 10)
uv run python scripts/play_from_db.py --all
```

This is useful for:
- Verifying audio quality without consuming ElevenLabs API credits
- Testing audio device configuration
- Replaying a specific utterance for debugging

## Rules for New Tests

- Mock all external calls: `httpx`, `motor`, `nats`
- No test requires running infrastructure
- Async tests work automatically via `asyncio_mode = auto` — no decorator needed
- Name: `test_<what_it_does>_<expected_outcome>`
