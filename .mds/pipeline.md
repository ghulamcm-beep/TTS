
● Done. Now here's how the full audio pipeline actually works:

  ---
  How the audio pipeline works

  ElevenLabs API
        │  HTTP stream (raw PCM bytes, 22050Hz 16-bit mono)
        ▼
  ElevenLabsSynthesizer.synthesize()
        │  async generator — yields 4096-byte chunks
        ▼
  TTSService._buffered()          ← tees the stream
        ├──► audio_buffer[]       ← accumulates all bytes for GridFS
        └──► AudioPlayer.play()
                 │
                 │  np.frombuffer(chunk, dtype=int16)
                 │  upmix mono→stereo if device needs 2ch
                 ▼
           sounddevice.OutputStream
                 │
                 │  PCM samples pushed to OS audio layer
                 ▼
           PulseAudio (Linux audio server)
                 │
                 ├──► physical speakers / headphones
                 └──► virtual_mic sink (virtual audio device)
                           │
                           └──► other apps can read this as a mic input
                                (e.g. a browser on a video call hears the agent speaking)

  Why both sounddevice AND PulseAudio?

  ┌─────────────┬─────────────────────────────────────────────────────────────────────────┐
  │  Component  │                                  Role                                   │
  ├─────────────┼─────────────────────────────────────────────────────────────────────────┤
  │ sounddevice │ Python library — opens an OutputStream and writes PCM samples to the OS │
  ├─────────────┼─────────────────────────────────────────────────────────────────────────┤
  │ PulseAudio  │ Linux audio server — receives those samples and routes them             │
  ├─────────────┼─────────────────────────────────────────────────────────────────────────┤
  │ virtual_mic │ A PulseAudio sink that looks like a microphone to other apps            │
  └─────────────┴─────────────────────────────────────────────────────────────────────────┘

  On Windows locally: sounddevice talks directly to the Windows audio stack (WASAPI/Realtek), PulseAudio is bypassed.

  On Linux/container: sounddevice → PulseAudio socket (mounted at /run/pulse/native) → virtual_mic sink → the agent's voice appears as a   
  mic input that a browser/WebRTC call can pick up.

  NATS is separate — it only carries interrupt signals (tts.interrupt subject), not audio. When main-agent wants to cut off speech
  mid-sentence, it publishes to NATS and the stop_event is set, breaking the playback loop immediately.

✻ Worked for 47s

❯ to what extant this system can be used                                                                                                                                            
● What this system can and can't do today                                                                                                                                                                                                                                             
  What it does well                                                                                                                        
  
  As a production TTS service for a single interview session:                                                                                - Agent text lands in MongoDB → voice plays within ~1-2 seconds (ElevenLabs flash model latency)                                         
  - Audio saved permanently in GridFS — every utterance is reviewable/replayable
  - Mid-speech interrupt via NATS (tts.interrupt) — agent stops speaking immediately
  - Audio cache — same text never costs API credits twice
  - Graceful degradation — if no audio device (container), still synthesizes and stores

  ---
  Hard limits right now

  Constraint: One interview at a time
  Detail: Serial queue — if two interviews are active simultaneously, the second one waits
  ────────────────────────────────────────
  Constraint: ElevenLabs free tier
  Detail: ~10,000 chars/month (flash model, 0.5 credits/char). An average interview turn ~200 chars → ~50 turns/month free
  ────────────────────────────────────────
  Constraint: Audio not browser-playable
  Detail: GridFS stores raw PCM, no WAV/MP3 header. A browser can't <audio src=...> it directly
  ────────────────────────────────────────
  Constraint: Linux only for virtual mic
  Detail: The virtual_mic → browser mic routing requires PulseAudio, which is Linux. Windows local = speakers only
  ────────────────────────────────────────
  Constraint: No retry on ElevenLabs failure
  Detail: If the API call fails, audio_url="played" is written — that turn is lost
  ────────────────────────────────────────
  Constraint: MongoDB replica set required
  Detail: Change streams won't work on a standalone MongoDB

  ---
  What it could feed into (with small additions)

  Current system
        │
        ├── interview recording platform   ← GridFS audio already there
        │        replay any session turn by turn
        │
        ├── WebRTC call (Linux)            ← virtual_mic already routes there
        │        candidate hears agent via browser mic input
        │
        ├── telephony (Twilio/Vonage)      ← stream PCM from GridFS over WebSocket
        │        agent speaks on a phone call
        │
        └── multi-interview scaling        ← needs one TTS container per active session
                 filter change stream by interview_id per instance

  ---
  What it is NOT

  - It does not do speech-to-text (STT) — candidate speech recognition is a separate service
  - It does not manage conversation turns — that is main-agent's job
  - It does not stream audio to a browser directly — that needs a WebSocket/WebRTC bridge
  - It is not a general-purpose TTS API — it only reacts to MongoDB inserts, no HTTP endpoint

  ---
  Practical ceiling today

  For your interview platform: comfortably handles one live interview at a time, with full audio persistence. For parallel interviews you'd
   run one TTS container per active session, each watching a specific interview_id — that's a config change, not a rewrite.
