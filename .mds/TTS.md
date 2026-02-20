TTS (Text-to-Speech) System - Complete Analysis

    Based on my analysis of the codebase, here's how the TTS system works end-to-end:

    ---

    📚 Libraries & Technologies Used


    ┌─────────────────┬───────────────────────────────────┬──────────────────────────────────────────────┐
    │ Component       │ Library/Tool                      │ Purpose                                      │
    ├─────────────────┼───────────────────────────────────┼──────────────────────────────────────────────┤
    │ TTS Engine      │ Piper TTS (piper-tts pip package) │ Neural text-to-speech synthesis              │
    │ Audio Output    │ PulseAudio (paplay command)       │ Raw PCM audio playback to virtual microphone │
    │ Message Queue   │ Redis Pub/Sub                     │ Event-driven communication between services  │
    │ Data Validation │ Pydantic v2                       │ Message schema validation                    │
    │ Async Runtime   │ asyncio                           │ Concurrent task execution                    │
    └─────────────────┴───────────────────────────────────┴──────────────────────────────────────────────┘


    ---

    🏗️ Architecture Overview

      1 ┌─────────────┐
      2 │   Brain     │  (AI generates response)
      3 │   Service   │
      4 └──────┬──────┘
      5        │ Publishes: brain.reply (text)
      6        ▼
      7 ┌─────────────────────────────────────────────────┐
      8 │              TTS Service                        │
      9 │  ┌──────────────────────────────────────────┐  │
     10 │  │  PlaybackController                      │  │
     11 │  │  - Manages speak() flow                  │  │
     12 │  │  - Generates utterance_id                │  │
     13 │  │  - Publishes tts.playing events          │  │
     14 │  └──────────┬───────────────────────────────┘  │
     15 │             │                                   │
     16 │  ┌──────────▼──────────┐  ┌──────────────────┐ │
     17 │  │ PiperSynthesizer    │  │   AudioPlayer    │ │
     18 │  │ - Subprocess: piper │  │ - Subprocess:    │ │
     19 │  │ - Text → PCM audio  │  │   paplay         │ │
     20 │  │ - Auto-restart      │  │ - Virtual mic    │ │
     21 │  └──────────┬──────────┘  └──────────────────┘ │
     22 │             │                                   │
     23 └─────────────┼───────────────────────────────────┘
     24               │ Raw PCM chunks (s16le, 22050Hz)
     25               ▼
     26      ┌────────────────┐
     27      │  PulseAudio    │
     28      │  virtual_mic   │
     29      └────────┬───────┘
     30               │
     31               ▼
     32      ┌────────────────┐
     33      │  Google Meet   │ (candidate hears AI voice)
     34      └────────────────┘

    ---

    🔄 Complete Flow (Step-by-Step)

    1. Brain Generates Response
     - Brain service receives transcribed text via text.heard Redis channel
     - LLM (Gemini) generates response
     - Response is published to brain.reply channel

    2. TTS Receives Text (main.py:70-80)

     1 async def _listen_brain_reply(self) -> None:
     2     async for channel, data in self.redis.subscribe(CHANNEL_BRAIN_REPLY):
     3         msg = BrainReply(**data)
     4         await self._controller.speak(msg.text)

    3. PlaybackController.speak() (playback_controller.py:41-112)
     - Generates unique `utterance_id` (UUID)
     - Publishes `tts.playing=True` to Redis (signals "AI is speaking")
     - Collects audio chunks from synthesizer
     - Plays audio via AudioPlayer
     - Publishes `tts.playing=False` when done

    4. PiperSynthesizer.synthesize() (synthesizer.py:68-117)
     - Sends text to Piper subprocess via stdin
     - Reads raw PCM audio from stdout (4096-byte chunks)
     - Auto-restarts Piper if it crashes
     - Yields audio chunks (format: s16le, mono, 22050Hz)

     1 # Piper command executed:
     2 piper --model /app/models/piper/en_US-amy-medium.onnx --output-raw

    5. AudioPlayer.play() (audio_player.py:26-48)
     - Spawns `paplay` subprocess for each utterance
     - Writes PCM audio to PulseAudio virtual device
     - Can be killed instantly for fast interruption

     1 # Command executed:
     2 paplay --device=virtual_mic --format=s16le --rate=22050 \
     3        --channels=1 --raw

    6. Audio Routing
     - PulseAudio virtual_mic is monitored by STT service
     - Audio is captured and sent to Google Meet
     - Candidate hears the AI voice

    ---

    ⚡ Interruption (Barge-in) Flow

    When user interrupts while AI is speaking:

     1. STT detects speech during TTS playback
     2. Control service receives audio.vad + tts.playing=True
     3. Barge-in detected → publishes control.stop_tts
     4. TTS receives interrupt:

     1    async def interrupt(self) -> None:
     2        self._interrupt_event.set()
     3        await self._player.stop()  # Kills paplay process
     5. AudioPlayer killed immediately (no waiting for playback to finish)
     6. Brain generation cancelled via control.cancel_generation

    ---

    📄 Key Files & Their Roles


    ┌─────────────────────────────────────────────┬────────────────────────────────────────────────────┬───────┐
    │ File                                        │ Purpose                                            │ Lines │
    ├─────────────────────────────────────────────┼────────────────────────────────────────────────────┼───────┤
    │ services/tts/src/tts/main.py                │ Service entry point, subscribes to Redis channels  │ 95    │
    │ services/tts/src/tts/playback_controller.py │ Coordinates synthesis + playback, publishes events │ 112   │
    │ services/tts/src/tts/synthesizer.py         │ Manages Piper subprocess, auto-restart logic       │ 117   │
    │ services/tts/src/tts/audio_player.py        │ Plays PCM via paplay command                       │ 48    │
    │ services/tts/src/tts/config.py              │ Configuration (model path, sample rate, etc.)      │ 20    │
    │ services/common/src/common/messages.py      │ Message schemas (TTSPlaying, BrainReply, etc.)     │ 180   │
    └─────────────────────────────────────────────┴────────────────────────────────────────────────────┴───────┘

    ---

    🔧 Configuration

    From config.py:

     1 pulse_server: str = "unix:/run/user/1000/pulse/native"  # PulseAudio socket
     2 virtual_mic: str = "virtual_mic"                        # Output device
     3 piper_model: str = "en_US-amy-medium"                   # Voice model
     4 piper_model_path: str = "/app/models/piper/en_US-amy-medium.onnx"
     5 output_sample_rate: int = 22050                         # Audio sample rate

    ---

    🎯 Redis Events (Pub/Sub)


    ┌────────────────┬──────────────────┬──────────┬──────────────┬────────────────────────────┐
    │ Event          │ Channel          │ Producer │ Consumer     │ Purpose                    │
    ├────────────────┼──────────────────┼──────────┼──────────────┼────────────────────────────┤
    │ BrainReply     │ brain.reply      │ Brain    │ TTS          │ AI response text           │
    │ TTSPlaying     │ tts.playing      │ TTS      │ STT, Control │ Echo suppression, barge-in │
    │ ControlStopTTS │ control.stop_tts │ Control  │ TTS          │ Interrupt playback         │
    └────────────────┴──────────────────┴──────────┴──────────────┴────────────────────────────┘

    ---

    🧪 Testing

    Tests located in services/tts/tests/:
     - test_playback_controller.py - Tests utterance IDs, interrupt logic, Redis events
     - test_audio_player.py - Tests audio player configuration

    ---

    📊 Performance Characteristics


    ┌──────────────────────┬─────────────────────────────────────┬────────────────────────────────┐
    │ Metric               │ Value                               │ Notes                          │
    ├──────────────────────┼─────────────────────────────────────┼────────────────────────────────┤
    │ Model                │ en_US-amy-medium                    │ Medium quality, balanced speed │
    │ Sample Rate          │ 22050 Hz                            │ Human speech optimized         │
    │ Audio Format         │ s16le (16-bit signed little-endian) │ Raw PCM, no compression        │
    │ Chunk Size           │ 4096 bytes                          │ ~93ms of audio per chunk       │
    │ First Chunk Timeout  │ 10s                                 │ Model load time                │
    │ Next Chunk Timeout   │ 0.5s                                │ End-of-utterance detection     │
    │ Interruption Latency │ <50ms                               │ Process kill (instant)         │
    └──────────────────────┴─────────────────────────────────────┴────────────────────────────────┘

    ---

    🐳 Docker Setup

    From docker-compose.yml:

     1 tts:
     2   build:
     3     context: .
     4     dockerfile: services/tts/Dockerfile
     5   environment:
     6     - PULSE_SERVER=tcp:meeting:4713  # Connect to meeting container's PulseAudio
     7     - VIRTUAL_MIC=virtual_mic
     8   volumes:
     9     - ./models:/app/models:ro  # Piper models mounted read-only

    ---

    🔍 Integration Points

    STT Service (services/stt/src/stt/main.py:81-92):
     - Listens to tts.playing for echo suppression
     - Disables VAD while AI is speaking (prevents false positives)

    Control Service (services/control/src/control/event_handler.py:103-113):
     - Listens to tts.playing for state machine transitions
     - tts.playing=True → State.SPEAKING
     - tts.playing=False → State.LISTENING

    Brain Service (services/brain/src/brain/response_builder.py):
     - Streams LLM tokens → splits into sentences → TTS can start early
     - Enables incremental synthesis (speak first sentence while generating rest)

    ---

    This is a fully event-driven, interruptible TTS pipeline designed for real-time conversational AI with sub-100ms interruption latency and robust error
    handling via auto-restart mechanisms.