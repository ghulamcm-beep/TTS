"""sounddevice audio player for PulseAudio virtual mic."""
import asyncio
import logging
from typing import AsyncGenerator, Optional

import numpy as np
import sounddevice as sd

from .config import config

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Plays PCM audio chunks via sounddevice to PulseAudio."""

    def __init__(self) -> None:
        self._stream: Optional[sd.OutputStream] = None
        self._is_playing = False

    def _get_device_id(self) -> Optional[int]:
        """Get PulseAudio virtual_mic device ID, or None for default."""
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if config.virtual_mic in dev["name"]:
                    logger.info(f"Found virtual_mic at device {i}: {dev['name']}")
                    return i
        except Exception as exc:
            logger.warning(f"Could not query audio devices: {exc}")

        logger.warning("virtual_mic not found, using default output device")
        return None

    async def play(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        stop_event: asyncio.Event,
    ) -> None:
        """
        Play audio chunks from async generator.

        Checks stop_event after each chunk for instant interruption (<50ms).
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
                if stop_event.is_set():
                    logger.info("Interrupt detected during playback")
                    break

                audio_data = np.frombuffer(chunk, dtype=np.int16)
                self._stream.write(audio_data)

            logger.info("Playback complete")

        except Exception as exc:
            logger.error(f"Playback error: {exc}")
            raise

        finally:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            self._is_playing = False

    def stop(self) -> None:
        """Stop playback immediately."""
        logger.info("Stopping audio playback")
        self._is_playing = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning(f"Error stopping stream: {exc}")
            finally:
                self._stream = None
