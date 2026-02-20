# Implementation Guide: TTS Service

**Version**: 1.0.0 | **Updated**: 2026-02-20

## Overview

This document provides detailed implementation guidance for the TTS service, including code examples, architecture decisions, and integration patterns.

---

## Architecture

```
┌─────────────┐
│  MongoDB    │
│  tts_queue  │
└──────┬──────┘
       │ Change Stream
       ▼
┌─────────────────────────────────────────┐
│           TTS Service                   │
│  ┌──────────────────────────────────┐   │
│  │  main.py (Event Loop)            │   │
│  │  - MongoDB change listener       │   │
│  │  - NATS subscriber               │   │
│  └──────────┬───────────────────────┘   │
│             │                             │
│  ┌──────────▼──────────┐  ┌────────────┐ │
│  │  tts_queue.py       │  │ interrupt_ │ │
│  │  - Parse document   │  │ handler.py │ │
│  │  - Validate text    │  │ - NATS sub │ │
│  └──────────┬──────────┘  └─────┬──────┘ │
│             │                    │         │
│  ┌──────────▼──────────┐  ┌─────▼──────┐ │
│  │  synthesizer.py     │  │ asyncio    │ │
│  │  - Piper subprocess │  │.Event      │ │
│  │  - Stream text→PCM  │  │ (stop)     │ │
│  └──────────┬──────────┘  └────────────┘ │
│             │                             │
│  ┌──────────▼──────────┐                  │
│  │  audio_player.py    │                  │
│  │  - sounddevice      │                  │
│  │  - OutputStream     │                  │
│  │  - Instant stop     │                  │
│  └──────────┬──────────┘                  │
└─────────────┼─────────────────────────────┘
              │ PCM 22050Hz, 16-bit, mono
              ▼
     ┌────────────────┐
     │  PulseAudio    │
     │  virtual_mic   │
     └────────┬───────┘
              │
              ▼
     ┌────────────────┐
     │   Browser      │ (Google Meet)
     └────────────────┘
```

---

## Module 1: Configuration (config.py)

```python
"""TTS Service Configuration"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable configuration loaded from environment variables."""
    
    # MongoDB
    mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_db: str = os.getenv("MONGODB_DB", "tts_service")
    tts_queue_collection: str = "tts_queue"
    
    # NATS
    nats_uri: str = os.getenv("NATS_URI", "nats://localhost:4222")
    nats_interrupt_subject: str = "tts.interrupt"
    nats_max_reconnect_attempts: int = 5
    
    # PulseAudio
    pulse_server: str = os.getenv("PULSE_SERVER", "unix:/run/user/1000/pulse/native")
    virtual_mic: str = os.getenv("VIRTUAL_MIC", "virtual_mic")
    
    # Piper TTS
    piper_model_path: str = os.getenv(
        "PIPER_MODEL_PATH",
        "/app/models/piper/en_US-amy-medium.onnx"
    )
    piper_command: str = "piper"
    
    # Audio
    sample_rate: int = 22050
    channels: int = 1
    dtype: str = "int16"
    chunk_size: int = 4096  # bytes
    
    # Timeouts
    first_chunk_timeout: float = 10.0  # seconds (model load time)
    next_chunk_timeout: float = 0.5    # seconds (end-of-utterance)
    
    # Performance
    interruption_latency_ms: int = 50


config = Config()
```

---

## Module 2: MongoDB Models (models/tts_queue.py)

```python
"""TTS Queue MongoDB Schema"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class TTSStatus(str, Enum):
    PENDING = "pending"
    PLAYING = "playing"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class TTSQueueDocument(BaseModel):
    """MongoDB document schema for TTS queue."""
    
    _id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    text: str
    status: TTSStatus = TTSStatus.PENDING
    priority: str = "normal"  # normal, high
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    interrupted_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

---

## Module 3: Status Updater (src/tts/status_updater.py)

```python
"""MongoDB status update helper."""
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
from ..models.tts_queue import TTSStatus
from .config import config


class StatusUpdater:
    """Updates TTS queue document status in MongoDB."""
    
    def __init__(self, mongo_client: AsyncIOMotorClient):
        self.db = mongo_client[config.mongodb_db]
        self.collection = self.db[config.tts_queue_collection]
    
    async def set_status(
        self,
        document_id: str,
        status: TTSStatus,
        error_message: Optional[str] = None
    ) -> None:
        """Update document status with appropriate timestamp."""
        
        update_fields = {
            "status": status.value,
        }
        
        # Set timestamp based on status
        if status == TTSStatus.PLAYING:
            update_fields["started_at"] = datetime.utcnow()
        elif status == TTSStatus.COMPLETED:
            update_fields["completed_at"] = datetime.utcnow()
        elif status == TTSStatus.INTERRUPTED:
            update_fields["interrupted_at"] = datetime.utcnow()
        elif status == TTSStatus.FAILED:
            update_fields["error_message"] = error_message
        
        await self.collection.update_one(
            {"_id": document_id},
            {"$set": update_fields}
        )
```

---

## Module 4: Piper Synthesizer (src/tts/synthesizer.py)

```python
"""Piper TTS subprocess manager."""
import asyncio
import logging
from typing import AsyncGenerator
from .config import config

logger = logging.getLogger(__name__)


class PiperSynthesizer:
    """Manages Piper TTS subprocess lifecycle and audio synthesis."""
    
    def __init__(self):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._restart_count = 0
        self._max_restarts = 3
    
    async def _start_piper(self) -> asyncio.subprocess.Process:
        """Start Piper subprocess."""
        cmd = [
            config.piper_command,
            "--model", config.piper_model_path,
            "--output-raw",
        ]
        
        logger.info(f"Starting Piper: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        return process
    
    async def _ensure_piper_running(self) -> None:
        """Ensure Piper is running, restart if crashed."""
        if self._process is None or self._process.returncode is not None:
            if self._restart_count >= self._max_restarts:
                raise RuntimeError(f"Piper crashed {self._restart_count} times, giving up")
            
            self._restart_count += 1
            logger.warning(f"Piper not running, restarting (attempt {self._restart_count})")
            self._process = await self._start_piper()
    
    async def synthesize(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Synthesize text to audio chunks.
        
        Yields PCM audio chunks (4096 bytes each).
        """
        async with self._lock:
            await self._ensure_piper_running()
            
            try:
                # Send text to Piper stdin
                self._process.stdin.write(text.encode('utf-8') + b'\n')
                await self._process.stdin.drain()
                
                # Read audio chunks from stdout
                chunk_count = 0
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            self._process.stdout.read(config.chunk_size),
                            timeout=config.first_chunk_timeout if chunk_count == 0 else config.next_chunk_timeout
                        )
                        
                        if not chunk:
                            # EOF - synthesis complete
                            break
                        
                        yield chunk
                        chunk_count += 1
                        
                    except asyncio.TimeoutError:
                        logger.warning("Piper chunk timeout - ending synthesis")
                        break
                
                logger.info(f"Synthesis complete: {chunk_count} chunks")
                
            except Exception as e:
                logger.error(f"Piper synthesis error: {e}")
                # Check if process crashed
                if self._process.returncode is not None:
                    stderr = await self._process.stderr.read()
                    logger.error(f"Piper stderr: {stderr.decode()}")
                    self._process = None  # Force restart on next call
                raise
    
    async def close(self) -> None:
        """Clean up Piper subprocess."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()
```

---

## Module 5: Audio Player (src/tts/audio_player.py)

```python
"""sounddevice audio player for PulseAudio virtual mic."""
import asyncio
import logging
import sounddevice as sd
from typing import Optional
from .config import config

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Plays PCM audio chunks via sounddevice to PulseAudio."""
    
    def __init__(self):
        self._stream: Optional[sd.OutputStream] = None
        self._is_playing = False
        self._stop_event = asyncio.Event()
    
    def _get_device_id(self) -> int:
        """Get PulseAudio virtual_mic device ID."""
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if config.virtual_mic in dev['name']:
                logger.info(f"Found virtual_mic at device {i}: {dev['name']}")
                return i
        
        # Fallback to default output device
        logger.warning(f"virtual_mic not found, using default device")
        return sd.default.device[1]
    
    async def play(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        stop_event: asyncio.Event
    ) -> None:
        """
        Play audio chunks from async generator.
        
        Checks stop_event for instant interruption.
        """
        device_id = self._get_device_id()
        
        self._stream = sd.OutputStream(
            device=device_id,
            samplerate=config.sample_rate,
            channels=config.channels,
            dtype=config.dtype,
            blocksize=config.chunk_size // 2,  # samples, not bytes
        )
        
        self._stream.start()
        self._is_playing = True
        
        try:
            async for chunk in audio_chunks:
                # Check for interrupt
                if stop_event.is_set():
                    logger.info("Interrupt detected during playback")
                    break
                
                # Convert bytes to numpy array
                import numpy as np
                audio_data = np.frombuffer(chunk, dtype=np.int16)
                
                # Write to sounddevice stream
                self._stream.write(audio_data)
            
            logger.info("Playback complete")
            
        except Exception as e:
            logger.error(f"Playback error: {e}")
            raise
        
        finally:
            self._stream.stop()
            self._stream.close()
            self._is_playing = False
    
    def stop(self) -> None:
        """Stop playback immediately."""
        logger.info("Stopping audio playback")
        self._is_playing = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
```

---

## Module 6: Interrupt Handler (src/tts/interrupt_handler.py)

```python
"""NATS subscriber for interrupt signals."""
import asyncio
import json
import logging
from typing import Optional
import nats
from .config import config

logger = logging.getLogger(__name__)


class InterruptHandler:
    """Subscribes to NATS interrupt channel."""
    
    def __init__(self):
        self._nc: Optional[nats.NATS] = None
        self._stop_event = asyncio.Event()
        self._subscription = None
    
    @property
    def stop_event(self) -> asyncio.Event:
        """Event that is set when interrupt received."""
        return self._stop_event
    
    async def connect(self) -> None:
        """Connect to NATS server."""
        self._nc = await nats.connect(
            config.nats_uri,
            max_reconnect_attempts=config.nats_max_reconnect_attempts,
        )
        
        # Subscribe to interrupt channel
        self._subscription = await self._nc.subscribe(
            config.nats_interrupt_subject,
            cb=self._handle_interrupt
        )
        
        logger.info(f"Subscribed to NATS subject: {config.nats_interrupt_subject}")
    
    async def _handle_interrupt(self, msg: nats.Msg) -> None:
        """Handle incoming interrupt message."""
        logger.info(f"Received interrupt: {msg.data.decode()}")
        self._stop_event.set()
    
    async def reset(self) -> None:
        """Clear interrupt flag for next utterance."""
        self._stop_event.clear()
    
    async def close(self) -> None:
        """Close NATS connection."""
        if self._subscription:
            await self._subscription.unsubscribe()
        if self._nc:
            await self._nc.close()
```

---

## Module 7: TTS Queue Listener (src/tts/tts_queue.py)

```python
"""MongoDB change stream listener for TTS queue."""
import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, AsyncGenerator
from .config import config
from .models.tts_queue import TTSQueueDocument

logger = logging.getLogger(__name__)


class TTSQueueListener:
    """Watches MongoDB tts_queue for new documents."""
    
    def __init__(self, mongo_client: AsyncIOMotorClient):
        self.db = mongo_client[config.mongodb_db]
        self.collection = self.db[config.tts_queue_collection]
        self._change_stream = None
    
    async def watch(self) -> AsyncGenerator[TTSQueueDocument, None]:
        """
        Watch for new TTS queue documents.
        
        Yields parsed TTSQueueDocument on insert.
        """
        # Watch for insert operations only
        pipeline = [{"$match": {"operationType": "insert"}}]
        
        self._change_stream = self.collection.watch(pipeline)
        
        logger.info("Watching MongoDB tts_queue for new documents")
        
        async for change in self._change_stream:
            try:
                full_doc = change["fullDocument"]
                doc = TTSQueueDocument(**full_doc)
                
                # Only process pending documents
                if doc.status.value == "pending":
                    logger.info(f"New TTS task: {doc._id} (session: {doc.session_id})")
                    yield doc
                    
            except Exception as e:
                logger.error(f"Error parsing queue document: {e}")
    
    async def close(self) -> None:
        """Close change stream."""
        if self._change_stream:
            await self._change_stream.close()
```

---

## Module 8: Main Service (src/tts/main.py)

```python
"""TTS Service entry point."""
import asyncio
import logging
import signal
from motor.motor_asyncio import AsyncIOMotorClient
from .config import config
from .tts_queue import TTSQueueListener
from .synthesizer import PiperSynthesizer
from .audio_player import AudioPlayer
from .interrupt_handler import InterruptHandler
from .status_updater import StatusUpdater
from .models.tts_queue import TTSStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TTSService:
    """Main TTS service orchestrator."""
    
    def __init__(self):
        self._mongo_client = AsyncIOMotorClient(config.mongodb_uri)
        self._queue_listener = TTSQueueListener(self._mongo_client)
        self._synthesizer = PiperSynthesizer()
        self._player = AudioPlayer()
        self._interrupt_handler = InterruptHandler()
        self._status_updater = StatusUpdater(self._mongo_client)
        self._running = False
    
    async def start(self) -> None:
        """Start TTS service."""
        logger.info("Starting TTS Service...")
        
        # Connect to NATS
        await self._interrupt_handler.connect()
        
        # Start watching MongoDB
        self._running = True
        
        async for doc in self._queue_listener.watch():
            if not self._running:
                break
            
            # Reset interrupt flag for new utterance
            await self._interrupt_handler.reset()
            
            # Process TTS task
            asyncio.create_task(self._process_task(doc))
    
    async def _process_task(self, doc) -> None:
        """Process a single TTS task."""
        try:
            logger.info(f"Processing task: {doc._id}")
            
            # Update status to playing
            await self._status_updater.set_status(doc._id, TTSStatus.PLAYING)
            
            # Synthesize text
            audio_chunks = self._synthesizer.synthesize(doc.text)
            
            # Play audio (with interrupt support)
            await self._player.play(
                audio_chunks,
                self._interrupt_handler.stop_event
            )
            
            # Check if interrupted
            if self._interrupt_handler.stop_event.is_set():
                await self._status_updater.set_status(doc._id, TTSStatus.INTERRUPTED)
                logger.info(f"Task interrupted: {doc._id}")
            else:
                await self._status_updater.set_status(doc._id, TTSStatus.COMPLETED)
                logger.info(f"Task completed: {doc._id}")
            
        except Exception as e:
            logger.error(f"Task failed: {doc._id} - {e}")
            await self._status_updater.set_status(
                doc._id, TTSStatus.FAILED, str(e)
            )
    
    async def stop(self) -> None:
        """Stop TTS service gracefully."""
        logger.info("Stopping TTS Service...")
        self._running = False
        
        await self._interrupt_handler.close()
        await self._queue_listener.close()
        await self._synthesizer.close()
        
        self._mongo_client.close()


async def main():
    """Entry point."""
    service = TTSService()
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        asyncio.create_task(service.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await service.start()
    except KeyboardInterrupt:
        pass
    finally:
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Testing Strategy

### Unit Tests

Test individual modules in isolation:
- `test_synthesizer.py`: Piper subprocess management
- `test_audio_player.py`: sounddevice configuration
- `test_interrupt_handler.py`: NATS message handling

### Integration Tests

Test end-to-end flows:
- `test_queue_to_audio.py`: MongoDB insert → Audio playback
- `test_interruption_flow.py`: NATS interrupt → Audio stop

### Contract Tests

Verify external contracts:
- `test_mongodb_schema.py`: Document schema validation
- `test_nats_protocol.py`: NATS message format

---

## Performance Optimization

### Achieving 100-200ms First Audio

1. **Pre-warm Piper**: Start Piper subprocess on service startup
2. **Reduce chunk size**: 2048 bytes instead of 4096 (faster first chunk)
3. **Async pipeline**: Overlap synthesis and playback
4. **MongoDB indexing**: Index on `status` field for faster change streams

### Achieving <50ms Interruption

1. **NATS Pub/Sub**: Sub-10ms message delivery
2. **asyncio.Event**: Instant flag check in playback loop
3. **sounddevice.stop()**: Immediate stream termination
4. **Check interrupt every chunk**: ~5ms latency per chunk check

---

## Docker Deployment

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    libpulse-dev \
    pulseaudio \
    && rm -rf /var/lib/apt/lists/*

# Install Piper
RUN pip install piper-tts

# Install Python dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application
COPY src/ /app/src/
COPY models/ /app/models/

WORKDIR /app

CMD ["python", "-m", "src.tts.main"]
```

---

## Troubleshooting

### Piper Not Found

```bash
# Verify Piper installation
which piper
piper --version
```

### virtual_mic Not Found

```bash
# List PulseAudio devices
pactl list sinks short

# Create virtual mic if missing
pactl load-module module-null-sink sink_name=virtual_mic
```

### NATS Connection Failed

```bash
# Check NATS is running
docker ps | grep nats

# Test connection
nats sub ">"
```

### sounddevice Device Error

```python
# List available devices
import sounddevice as sd
print(sd.query_devices())
```
