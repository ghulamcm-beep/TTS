# Research: ElevenLabs TTS API

**Feature**: `011-elevenlabs` | **Date**: 2026-02-20 | **Scope**: English-only, free tier

---

## 1. API Overview

ElevenLabs provides a REST + WebSocket TTS API. For real-time streaming synthesis the relevant endpoint is:

```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream
```

- Auth header: `xi-api-key: <YOUR_KEY>`
- Response: `application/octet-stream` (chunked transfer encoding — raw audio bytes stream)
- Cancel mid-stream: close the HTTP connection (httpx cancellation via `response.close()`)

---

## 2. Models

| Model ID | Languages | Latency | Best For |
|----------|-----------|---------|----------|
| `eleven_flash_v2_5` | 32 (incl. English) | ~75ms† | Real-time voice agents ✅ |
| `eleven_flash_v2` | English only | ~75ms† | English-only pipelines ✅ |
| `eleven_turbo_v2_5` | 32 | ~250-300ms | Balanced quality/speed |
| `eleven_multilingual_v2` | 29 | ~400ms+ | Quality, no speed req |
| `eleven_v3` | 70+ | N/A | Highest quality |

**† excludes network and application latency**

**Decision for this project**: `eleven_flash_v2_5` — lowest latency, supports English, good quality for conversational AI.

---

## 3. Output Formats

The `output_format` query parameter controls codec and sample rate:

| Format | Description |
|--------|-------------|
| `pcm_22050` | Raw PCM, 22050 Hz, 16-bit, mono ← **USE THIS** |
| `pcm_16000` | Raw PCM, 16000 Hz, 16-bit, mono |
| `pcm_24000` | Raw PCM, 24000 Hz, 16-bit, mono |
| `pcm_44100` | Raw PCM, 44100 Hz, 16-bit, mono |
| `mp3_22050_32` | MP3, 22050 Hz, 32 kbps |
| `mp3_44100_128` | MP3, 44100 Hz, 128 kbps |

**`pcm_22050` is the ideal choice**: raw PCM matches existing sounddevice config (22050Hz, int16, mono). No decoding overhead. Directly writable to `sd.OutputStream`.

---

## 4. Free Tier Limits

| Attribute | Value |
|-----------|-------|
| Monthly credits | 20,000 credits |
| Credits per character | 1 credit per character (standard models) |
| Flash models cost | 1 credit per 2 characters |
| Max characters per request | 2,500 characters |
| Use type | Non-commercial only |
| Approx. monthly audio | ~10 minutes of speech |

**Implication for this project**: Flash models are 0.5 credits/char → effectively 40,000 characters/month on free tier. Good for testing.

**Important constraints**:
- Free tier has concurrent request limits (typically 2 concurrent streams)
- Rate limiting returns HTTP 429 — must handle with exponential backoff
- Quota exceeded returns HTTP 401/403 — must fail gracefully

---

## 5. English Voices (Free Tier)

Popular free English voices and their IDs:

| Name | Voice ID | Style |
|------|----------|-------|
| Rachel | `21m00Tcm4TlvDq8ikWAM` | Calm, narration |
| Adam | `pNInz6obpgDQGcFmaJgB` | Deep, narration |
| Bella | `EXAVITQu4vr4xnSDxMaL` | Expressive |
| Elli | `MF3mGyEYCl7XYWbV9V6O` | Emotional |
| Josh | `TxGEqnHWrfWFTfGW9XjX` | Deep |
| Arnold | `VR6AewLTigWG4xSOukaG` | Crisp |
| Domi | `AZnzlk1XvdvUeBnXmlld` | Strong |

**Default**: Rachel (`21m00Tcm4TlvDq8ikWAM`) — most stable, widely used for conversational AI. Configurable via `ELEVENLABS_VOICE_ID` env var.

---

## 6. Python SDK

**Package**: `elevenlabs`

```bash
pip install elevenlabs
```

**Sync streaming**:
```python
from elevenlabs.client import ElevenLabs

client = ElevenLabs(api_key="YOUR_KEY")
audio_stream = client.text_to_speech.stream(
    text="Hello world",
    voice_id="21m00Tcm4TlvDq8ikWAM",
    model_id="eleven_flash_v2_5",
    output_format="pcm_22050",
)
for chunk in audio_stream:
    if isinstance(chunk, bytes):
        # write to sounddevice
        pass
```

**Async client** (`AsyncElevenLabs`):
```python
from elevenlabs.client import AsyncElevenLabs

client = AsyncElevenLabs(api_key="YOUR_KEY")
# Note: async streaming uses httpx under the hood
# Mid-stream cancellation: break out of iteration + close response
```

**Raw httpx streaming** (better control for cancellation):
```python
import httpx

async with httpx.AsyncClient() as client:
    async with client.stream(
        "POST",
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
        headers={"xi-api-key": api_key},
        params={"output_format": "pcm_22050"},
        json={"text": text, "model_id": "eleven_flash_v2_5"},
    ) as response:
        async for chunk in response.aiter_bytes(chunk_size=4096):
            if stop_event.is_set():
                break  # close connection implicitly on exit
            yield chunk
```

**Mid-stream cancellation**: breaking out of the `async for` loop causes httpx to close the connection. The synthesizer checks `stop_event` between chunks — same pattern as Piper.

---

## 7. Latency Analysis

For real-time conversational AI, full end-to-end latency = API latency + network latency.

| Component | Latency |
|-----------|---------|
| ElevenLabs Flash inference | ~75ms |
| Network RTT (EU/US server) | ~20-80ms |
| First audio chunk delivery | ~95-155ms total |
| Subsequent chunks | ~20-50ms each |
| sounddevice write | <1ms |
| NATS interrupt detection | <10ms |
| Stop event check (per chunk) | <1ms |

**Expected first audio**: 100-200ms (matching Piper target). Actual depends on server distance.

**Interruption**: Since we check `stop_event` per chunk (4096 bytes = ~93ms at 22050Hz), worst-case interruption latency is one chunk duration. But sounddevice stream can be stopped immediately regardless, so effective interruption is <50ms.

---

## 8. Error Codes

| HTTP Code | Meaning | Action |
|-----------|---------|--------|
| 200 | Success streaming | Continue |
| 401 | Invalid API key | Fail service startup |
| 403 | Quota exceeded | Log error, set status=failed |
| 422 | Validation error (bad params) | Log error, set status=failed |
| 429 | Rate limited | Retry with exponential backoff (max 3) |
| 500 | ElevenLabs server error | Retry once, then fail |

---

## 9. Comparison: ElevenLabs vs Piper

| Aspect | Piper (old) | ElevenLabs (new) |
|--------|------------|-----------------|
| Latency | 100-200ms (local) | ~75ms API + network |
| Quality | Good (medium model) | Excellent |
| Cost | Free (self-hosted) | 20k credits/month free |
| Internet required | No | Yes |
| Model size | ~100MB on disk | No local model |
| Languages | English only | 32 languages |
| Reliability | No API dependency | API quota/downtime risk |
| Interruption | Break stdin loop | Break HTTP stream |

---

## 10. What Stays the Same

The following architecture components are **unchanged**:
- MongoDB change stream listener (`tts_queue.py`)
- NATS interrupt handler (`interrupt_handler.py`)
- sounddevice audio player (`audio_player.py`) — PCM 22050Hz still used
- Status updater (`status_updater.py`)
- Main service orchestrator (`main.py`)
- Docker + docker-compose infrastructure

**Only `synthesizer.py` changes**: Piper subprocess → ElevenLabs HTTP stream.

---

## 11. Key Decisions

1. **Use `eleven_flash_v2_5`** over `eleven_flash_v2` — same latency, supports 32 languages (future-proof), same cost
2. **Use `pcm_22050`** output format — zero decoding, directly compatible with existing sounddevice setup
3. **Use raw httpx** for async streaming (not SDK) — gives direct control over cancellation and chunk iteration
4. **Voice configurable via env var** — default Rachel, overridable via `ELEVENLABS_VOICE_ID`
5. **Retry on 429** (rate limit) with exponential backoff, max 3 attempts
6. **Fail fast on 401/403** — no point retrying auth/quota errors

Sources:
- [ElevenLabs Stream API](https://elevenlabs.io/docs/api-reference/text-to-speech/stream)
- [ElevenLabs Models](https://elevenlabs.io/docs/overview/models)
- [ElevenLabs Python SDK](https://github.com/elevenlabs/elevenlabs-python)
- [PCM Output Format](https://elevenlabs.io/blog/pcm-output-format)
- [Free Tier Limits](https://word-spinner.com/blog/what-is-the-free-limit-for-elevenlabs/)
