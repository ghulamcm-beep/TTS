"""TTS Service entry point."""
import asyncio
import logging
import os
import signal

from motor.motor_asyncio import AsyncIOMotorClient

from .config import config
from .logging_config import setup_logging
from .tts_queue import TranscriptListener
from .synthesizer import ElevenLabsSynthesizer
from .audio_player import AudioPlayer
from .interrupt_handler import InterruptHandler
from .status_updater import TranscriptUpdater
from models.tts_queue import TranscriptDocument

logger = logging.getLogger(__name__)


class TTSService:
    """Main TTS service orchestrator."""

    def __init__(self) -> None:
        self._mongo_client = AsyncIOMotorClient(config.mongodb_uri)
        self._transcript_listener = TranscriptListener(self._mongo_client)
        self._synthesizer = ElevenLabsSynthesizer()
        self._player = AudioPlayer()
        self._interrupt_handler = InterruptHandler()
        self._transcript_updater = TranscriptUpdater(self._mongo_client)
        self._running = False
        self._nats_enabled = False

    async def start(self) -> None:
        """Start TTS service."""
        logger.info("Starting TTS Service...")

        # NATS is optional — if unavailable, interrupt feature is silently disabled
        if config.nats_uri:
            try:
                await self._interrupt_handler.connect()
                self._nats_enabled = True
                logger.info("NATS interrupt feature enabled")
            except Exception as exc:
                logger.warning(
                    f"NATS unavailable ({exc}) — interrupt feature disabled"
                )
        else:
            logger.info("NATS_URI not set — interrupt feature disabled")

        self._running = True

        async for doc in self._transcript_listener.watch():
            if not self._running:
                break

            # Reset interrupt flag for new utterance
            await self._interrupt_handler.reset()

            # Process one transcript at a time — no concurrent synthesis
            await self._process_transcript(doc)

    async def _process_transcript(self, doc: TranscriptDocument) -> None:
        """Synthesize and play a single agent transcript."""
        logger.info(
            f"Processing transcript: interview={doc.interview_id} chars={len(doc.text)}"
        )

        try:
            audio_chunks = self._synthesizer.synthesize(doc.text)
            await self._player.play(audio_chunks, self._interrupt_handler.stop_event)

            # Always mark as played regardless of interrupt — audio was handled
            await self._transcript_updater.mark_played(doc.id)

            if self._interrupt_handler.stop_event.is_set():
                logger.info(f"Transcript interrupted: {doc.id}")
            else:
                logger.info(f"Transcript completed: {doc.id}")

        except Exception as exc:
            logger.error(f"Transcript processing failed: {doc.id} — {exc}")
            # Still mark as played to unblock main-agent
            try:
                await self._transcript_updater.mark_played(doc.id)
            except Exception as update_exc:
                logger.error(f"Failed to mark transcript as played: {update_exc}")

    async def stop(self) -> None:
        """Stop TTS service gracefully."""
        logger.info("Stopping TTS Service...")
        self._running = False

        if self._nats_enabled:
            await self._interrupt_handler.close()
        await self._transcript_listener.close()
        await self._synthesizer.close()
        self._mongo_client.close()
        logger.info("TTS Service stopped")


async def main() -> None:
    """Async entry point."""
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    service = TTSService()

    loop = asyncio.get_event_loop()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        asyncio.create_task(service.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):
            # Windows does not support add_signal_handler for all signals
            pass

    try:
        await service.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await service.stop()


def main_sync() -> None:
    """Synchronous entry point for uv script."""
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
