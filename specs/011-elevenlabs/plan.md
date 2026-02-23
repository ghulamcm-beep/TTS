# Implementation Plan: ElevenLabs TTS Synthesizer

**Branch**: `11` | **Date**: 2026-02-20 | **Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md)

---

## Summary

Replace `src/tts/synthesizer.py` (Piper subprocess) with `ElevenLabsSynthesizer` that streams PCM audio from the ElevenLabs HTTP API. All other modules remain **unchanged**: `tts_queue.py`, `audio_player.py`, `interrupt_handler.py`, `status_updater.py`, `main.py`, `models/tts_queue.py`.

**Diff size**: ~1 file rewritten + config.py extended + new tests.

---

## Constitution Check

- ✅ **Streaming-First**: Stream text → stream PCM chunks → immediate sounddevice playback. No buffering.
- ✅ **Interruptible <50ms**: HTTP stream closed via httpx cancellation when `stop_event` set. sounddevice.stop() called immediately.
- ✅ **sounddevice for Audio**: `audio_player.py` unchanged — still uses `sd.OutputStream` with `pcm_22050` format.
- ✅ **NATS for Real-Time Control**: `interrupt_handler.py` unchanged.
- ✅ **MongoDB Change Streams**: `tts_queue.py` unchanged.
- ✅ **Test-First (TDD)**: Tests written before implementation.
- ✅ **Simplicity**: Smallest viable change — only synthesizer.py replaced.

---

## Technical Decisions

### Decision 1: HTTP Streaming vs WebSocket

**Use HTTP chunked streaming** (`POST /v1/text-to-speech/{voice_id}/stream`), not WebSocket.

- HTTP streaming is simpler (no connection lifecycle management)
- WebSocket adds value only for multi-turn streaming input (sending text in chunks); we send complete text at once
- httpx async streaming (`aiter_bytes`) is clean and cancellable

### Decision 2: Use raw httpx, not ElevenLabs SDK

**Use `httpx` directly**, not `elevenlabs` Python SDK.

- SDK's async streaming has known issues with mid-stream cancellation
- httpx gives direct control: `response.aclose()` for instant cancellation
- Fewer dependencies, better testability (mock httpx directly)
- SDK can be added later if needed; httpx is already a transitive dependency

### Decision 3: `pcm_22050` output format

**Raw PCM, 22050Hz, 16-bit, mono** — identical to Piper output.

- Zero decoding overhead (no mp3/opus decode)
- Direct compatibility with existing `audio_player.py` (no changes needed)
- `np.frombuffer(chunk, dtype=np.int16)` works identically

### Decision 4: `eleven_flash_v2_5` model

Lowest inference latency (~75ms). Supports 32 languages (future-proof). English quality is excellent.

### Decision 5: Retry strategy

Retry on HTTP 429 only (rate limit). Max 3 retries, exponential backoff starting at 1s.
Fail immediately on 401 (bad key), 403 (quota), 422 (invalid params).

---

## Project Structure

### Changed Files

```text
src/tts/
├── synthesizer.py        ← REWRITE: ElevenLabsSynthesizer (was PiperSynthesizer)
├── config.py             ← EXTEND: add ELEVENLABS_API_KEY, VOICE_ID, MODEL_ID

tests/
├── unit/
│   └── test_synthesizer.py     ← REWRITE: ElevenLabs-specific tests
├── contract/
│   └── test_elevenlabs_contract.py  ← NEW: API contract tests
├── integration/
│   └── test_elevenlabs_flow.py      ← NEW: end-to-end flow with mocks
```

### Unchanged Files

```text
src/tts/
├── main.py               ← NO CHANGE
├── tts_queue.py          ← NO CHANGE
├── audio_player.py       ← NO CHANGE
├── interrupt_handler.py  ← NO CHANGE
├── status_updater.py     ← NO CHANGE
├── logging_config.py     ← NO CHANGE

models/tts_queue.py       ← NO CHANGE
tests/contract/test_mongodb_schema.py   ← NO CHANGE
tests/contract/test_nats_protocol.py    ← NO CHANGE
tests/unit/test_interrupt_handler.py    ← NO CHANGE
tests/unit/test_status_updater.py       ← NO CHANGE
tests/integration/test_queue_to_audio.py   ← NO CHANGE
tests/integration/test_interruption_flow.py ← NO CHANGE
tests/integration/test_error_recovery.py    ← UPDATE: add ElevenLabs error scenarios
```

---

## Module Design

### Config Extension (`src/tts/config.py`)

```python
# New fields
elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
elevenlabs_model_id: str = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
elevenlabs_output_format: str = "pcm_22050"
elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"
elevenlabs_max_retries: int = 3
elevenlabs_retry_base_delay: float = 1.0
elevenlabs_stream_timeout: float = 10.0  # first chunk timeout
```

### ElevenLabsSynthesizer (`src/tts/synthesizer.py`)

```python
class ElevenLabsSynthesizer:
    """Streams PCM audio from ElevenLabs TTS API."""

    async def synthesize(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        POST to /v1/text-to-speech/{voice_id}/stream
        Yields raw PCM bytes (pcm_22050 = s16le, 22050Hz, mono)
        Handles retries on 429, raises on 401/403/422
        """

    async def close(self) -> None:
        """Cancel any in-progress request."""
```

**Key implementation pattern**:
```python
async with httpx.AsyncClient(timeout=httpx.Timeout(config.elevenlabs_stream_timeout)) as client:
    async with client.stream(
        "POST",
        f"{config.elevenlabs_base_url}/text-to-speech/{config.elevenlabs_voice_id}/stream",
        headers={"xi-api-key": config.elevenlabs_api_key},
        params={"output_format": config.elevenlabs_output_format},
        json={
            "text": text,
            "model_id": config.elevenlabs_model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes(chunk_size=config.chunk_size):
            if stop_event.is_set():
                return  # closes connection on context exit
            yield chunk
```

---

## Dependency Update

```
# Add to requirements.txt / pyproject.toml
httpx>=0.27.0        # async HTTP client (may already be transitive dep)
```

Remove:
```
# No longer needed (but keep in case Piper branch merges)
# piper-tts (was never in requirements.txt anyway)
```

---

## Testing Strategy

### Unit Tests (no network, no real API)

- Mock `httpx.AsyncClient` using `pytest-mock` or `respx`
- Test: successful stream → yields chunks
- Test: 429 → retries with backoff
- Test: 401 → raises immediately
- Test: stop_event set → stream exits cleanly
- Test: network timeout → raises

### Contract Tests

- Verify request format: headers, params, body schema
- Verify PCM chunk format is valid int16 data
- Verify `xi-api-key` header is set (not logged)

### Integration Tests (mocked HTTP)

- Full flow: text → ElevenLabs mock → PCM chunks → (mock) sounddevice
- Interrupt during stream: verify early exit
- Error propagates to status=failed

### Manual Testing (with real API key)

- Run service with `ELEVENLABS_API_KEY` set
- Insert MongoDB document → verify audio plays
- Publish NATS interrupt → verify stops
- Check credits used in ElevenLabs dashboard

---

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| httpx instead of SDK | Mid-stream cancellation control | SDK has known async cancellation issues |
| Retry logic (429) | Free tier rate limiting | Silent failure hides quota issues |
| pcm_22050 format | Zero decode overhead | mp3 requires audioop/pydub decode |

---

## Quickstart (after implementation)

```bash
# Set API key
export ELEVENLABS_API_KEY=your_key_here

# Install httpx
uv add httpx

# Run tests (mocked - no API calls)
uv run pytest tests/

# Test with real API
export ELEVENLABS_API_KEY=your_key_here
docker-compose up -d mongodb nats
uv run tts
# In another terminal:
mongosh --eval 'db.tts_queue.insertOne({session_id:"test",text:"Hello from ElevenLabs",status:"pending",priority:"normal",created_at:new Date()})'
```

---

## Risks

1. **Network dependency**: ElevenLabs API unavailable → entire TTS fails. Mitigation: graceful error + status=failed, service keeps watching queue.
2. **Free tier quota exhaustion**: 20k credits/month depletes during testing. Mitigation: keep test texts short, use mocks for unit/integration tests.
3. **Latency spike**: Server-side latency varies by region. Mitigation: configurable `elevenlabs_stream_timeout`, log first-chunk timing.
