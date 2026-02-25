# 10 — Troubleshooting

---

## Audio Issues

### No audio / `Invalid number of channels [PaErrorCode -9998]`

**Symptom**:
```json
{"level":"WARNING","message":"Audio playback unavailable: Error opening OutputStream: Invalid number of channels [PaErrorCode -9998] — synthesizing to DB only"}
```

**Cause**: `AUDIO_DEVICE_ID` points to a device that does not support the configured channel count (usually mono on a stereo-only device), or the device index is invalid.

**Fix**:
1. List devices: `uv run python -c "import sounddevice as sd; print(sd.query_devices())"`
2. Find your speaker/headphone device (look for output devices with `out > 0`)
3. Update `AUDIO_DEVICE_ID` in `.env` with the correct index
4. Or clear `AUDIO_DEVICE_ID=` to use the system default

---

### No audio — headphones unplugged

**Symptom**: Worked with headphones, silent without.

**Cause**: `AUDIO_DEVICE_ID=4` was set to the headphone device specifically. When headphones are unplugged, device 4 may not be available.

**Fix**: The service now validates the device and falls back to system default automatically. If you still see the issue, clear `AUDIO_DEVICE_ID=` in `.env` to always use the system default.

---

### Audio plays but choppy / distorted

**Cause**: `chunk_size` may be too small for the system's audio buffer, causing underruns.

**Fix**: Increase `chunk_size` in `config.py`:
```python
chunk_size: int = 8192   # increase from 4096
```
Also increase `blocksize` in `AudioPlayer` (it is `chunk_size // 2`).

---

### No audio in Docker

**Expected behaviour**: In Docker, audio goes to the PulseAudio virtual mic, not your laptop speakers. This is correct.

To verify audio is flowing:
```bash
docker compose exec pulseaudio pactl list sink-inputs
```

If empty, TTS is not writing to PulseAudio. Check:
- PulseAudio container is healthy: `docker compose ps`
- `pulse_socket` volume is shared correctly: `docker compose exec tts ls /run/pulse/`
- `PULSE_SERVER` and `VIRTUAL_MIC` are set in the TTS container

---

## MongoDB Issues

### `The $changeStream stage is only supported on replica sets`

**Symptom**:
```json
{"level":"WARNING","message":"MongoDB change stream error (attempt 1/5): ..."}
```

**Cause**: MongoDB is running as standalone (not replica set).

**Fix**: Start MongoDB with `--replSet rs0` and initialise:
```bash
# Via Docker
docker run -d --name mongo -p 27017:27017 mongo:7.0 mongod --replSet rs0 --bind_ip_all
sleep 5
docker exec mongo mongosh --eval "rs.initiate({_id:'rs0',members:[{_id:0,host:'localhost:27017'}]})"

# Verify
mongosh --eval "rs.status().ok"   # should print 1
```

---

### Service starts but no synthesis triggered

**Symptom**: Document inserted into MongoDB but TTS service does nothing.

**Check 1**: Is the document schema correct?
```javascript
// CORRECT — triggers synthesis
{ speaker: "agent", audio_url: null, text: "Hello" }

// WRONG — audio_url missing (treated as null in JS but Mongo stores it as missing)
{ speaker: "agent", text: "Hello" }

// WRONG — wrong speaker
{ speaker: "Agent", audio_url: null, text: "Hello" }  // case-sensitive!

// WRONG — already processed
{ speaker: "agent", audio_url: "played", text: "Hello" }
```

**Check 2**: Is the Change Stream filter matching?
```javascript
mongosh interviews --eval "
  db.transcripts.find({speaker:'agent', audio_url:null}).count()
"
```

**Check 3**: Is MongoDB URI correct?
- Must include `?replicaSet=rs0`
- `MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0` ✓
- `MONGODB_URI=mongodb://localhost:27017` ✗ (no replica set)

---

### `Max MongoDB reconnection attempts reached`

**Symptom**: Service logs this error and stops watching.

**Cause**: MongoDB was unavailable for too long (>5 retries with exponential backoff = up to ~30s).

**Fix**: Restart the service. It will reconnect and start watching again.

To prevent this in production, add `restart: unless-stopped` to `docker-compose.yml`.

---

## ElevenLabs API Issues

### `ElevenLabsAuthError` (401)

**Cause**: `ELEVENLABS_API_KEY` is empty, invalid, or expired.

**Fix**:
1. Check `.env`: `ELEVENLABS_API_KEY=sk_your_key_here` (not empty)
2. Verify the key at https://elevenlabs.io → Profile → API Keys
3. Restart the service after updating `.env`

---

### `ElevenLabsRateLimitError` (429)

**Cause**: API quota exhausted or rate limit hit.

**Free tier**: 10,000 characters/month. Each request costs `len(text)` characters.

**Fix**:
- Wait for quota to reset (monthly)
- Upgrade to a paid ElevenLabs plan
- Cache audio aggressively — use `play_from_db.py` to replay stored audio instead of re-synthesising

---

### Synthesis very slow (>3 seconds)

**Cause**: ElevenLabs server load, or network latency to ElevenLabs servers.

**Fix**:
- This is network-dependent; no code change will fix it
- Try `eleven_flash_v2_5` if you are using a different model
- Check ElevenLabs status page

---

### `ElevenLabsNetworkError` (timeout)

**Cause**: Connection to ElevenLabs timed out. Default timeout is 10 seconds.

**Fix**: Usually transient. The service will process the next document normally.

If consistently timing out, increase the timeout in `config.py`:
```python
elevenlabs_connect_timeout: float = 30.0
```

---

## NATS Issues

### `NATS unavailable — interrupt feature disabled`

**Symptom**:
```json
{"level":"WARNING","message":"NATS unavailable (...) — interrupt feature disabled"}
```

This is not an error — it is expected when `NATS_URI` is empty or NATS is not reachable. The service runs normally without interrupts.

**If you want interrupts**: Set `NATS_URI=nats://localhost:4222` and start NATS:
```bash
docker run -d --name nats -p 4222:4222 nats:2.10-alpine -js
```

---

### Interrupt sent but synthesis does not stop

**Check 1**: Is NATS connected?
```json
{"level":"INFO","message":"Subscribed to NATS subject: tts.interrupt"}
```
This log line should appear at startup if NATS is connected.

**Check 2**: Is the subject correct?
```bash
nats pub tts.interrupt '{}'     # correct
nats pub tts_interrupt '{}'     # wrong (underscore)
```

**Check 3**: Is stop_event being reset correctly?
Each new utterance calls `InterruptHandler.reset()` which clears the event. If an interrupt arrives between utterances, it is cleared at the start of the next one.

---

## Docker Issues

### `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`

**Cause**: Docker Desktop is not running (Windows).

**Fix**: Open Docker Desktop from the Start Menu and wait for it to fully start before running `docker compose` commands.

---

### `docker compose build` fails

**Common causes**:
1. No internet access to download base image (`python:3.11-slim`)
2. `pyproject.toml` or `uv.lock` has a dependency that can't install (check build output)
3. `uv.lock` is out of sync with `pyproject.toml` — run `uv lock` locally first

---

### TTS container exits immediately

```bash
docker compose logs tts
```

Common reasons:
- `ELEVENLABS_API_KEY` not set in `.env`
- MongoDB not healthy yet (increase `mongo-init` wait time)
- Python import error (check logs for `ImportError` or `ModuleNotFoundError`)

---

## General Debugging

### Enable debug logging

```env
LOG_LEVEL=DEBUG
```

This logs every HTTP request/response (httpx), each chunk count, and all internal state changes.

### Inspect MongoDB state

```bash
# All transcripts
mongosh interviews --eval "db.transcripts.find({}).sort({timestamp:-1}).limit(5).pretty()"

# Unprocessed (audio_url = null)
mongosh interviews --eval "db.transcripts.find({speaker:'agent', audio_url:null}).count()"

# GridFS files
mongosh interviews --eval "db.getCollection('audio.files').find({}).sort({uploadDate:-1}).limit(5).pretty()"
```

### Check what audio devices are available

```bash
uv run python -c "
import sounddevice as sd
devices = sd.query_devices()
print(devices)
print('\nDefault output:', sd.default.device)
"
```

### Manually test ElevenLabs API key

```bash
curl -X POST https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM/stream \
  -H "xi-api-key: YOUR_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello","model_id":"eleven_flash_v2_5"}' \
  --output test.pcm

# If successful, test.pcm will be non-empty
wc -c test.pcm
```
