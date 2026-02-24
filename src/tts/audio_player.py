"""sounddevice audio player."""
import asyncio
import logging
from typing import AsyncGenerator, Optional

import numpy as np
import sounddevice as sd

from .config import config

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Plays mono PCM audio chunks via sounddevice."""

    def __init__(self) -> None:
        self._stream: Optional[sd.OutputStream] = None
        self._is_playing = False

    def _get_device_id(self) -> Optional[int]:
        """
        Resolve output device:
        1. AUDIO_DEVICE_ID env var (validated — skipped if device not usable)
        2. virtual_mic name match (Linux PulseAudio)
        3. None → sounddevice system default
        """
        if config.audio_device_id is not None:
            try:
                sd.query_devices(config.audio_device_id, kind="output")
                logger.info(f"Using configured audio device: {config.audio_device_id}")
                return config.audio_device_id
            except Exception as exc:
                logger.warning(
                    f"Configured device {config.audio_device_id} unavailable ({exc})"
                    " — falling back to system default"
                )

        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if config.virtual_mic in dev["name"]:
                    logger.info(f"Found virtual_mic at device {i}: {dev['name']}")
                    return i
        except Exception as exc:
            logger.warning(f"Could not query audio devices: {exc}")

        logger.info("Using system default output device")
        return None

    def _get_out_channels(self, device_id: Optional[int]) -> int:
        """Return the number of output channels the device requires (min 1)."""
        try:
            info = sd.query_devices(device_id, kind="output")
            ch = int(info["default_low_output_latency"] and info.get("max_output_channels", 1))
            ch = int(info.get("max_output_channels", 1))
            return max(1, min(ch, 2))  # cap at stereo
        except Exception:
            return 1

    async def play(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        stop_event: asyncio.Event,
    ) -> None:
        """
        Play mono PCM audio chunks from async generator.

        Automatically upmixes mono → stereo when the output device requires it.
        Checks stop_event after each chunk for interruption.
        """
        device_id = self._get_device_id()
        out_channels = self._get_out_channels(device_id)

        logger.info(f"Opening audio stream: device={device_id} channels={out_channels}")

        self._stream = sd.OutputStream(
            device=device_id,
            samplerate=config.sample_rate,
            channels=out_channels,
            dtype=config.dtype,
            blocksize=config.chunk_size // 2,
        )
        self._stream.start()
        self._is_playing = True

        try:
            async for chunk in audio_chunks:
                if stop_event.is_set():
                    logger.info("Interrupt detected during playback")
                    break

                # int16 alignment
                if len(chunk) % 2:
                    chunk = chunk[:-1]
                if not chunk:
                    continue

                mono = np.frombuffer(chunk, dtype=np.int16)

                if out_channels == 2:
                    # upmix mono → stereo by duplicating the channel
                    stereo = np.column_stack((mono, mono))
                    self._stream.write(stereo)
                else:
                    self._stream.write(mono)

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
