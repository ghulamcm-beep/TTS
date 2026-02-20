"""TTS Service entry point."""
import asyncio
import logging
import os
import signal

from motor.motor_asyncio import AsyncIOMotorClient

from .config import config
from .logging_config import setup_logging
from .tts_queue import TTSQueueListener
from .synthesizer import PiperSynthesizer
from .audio_player import AudioPlayer
from .interrupt_handler import InterruptHandler
from .status_updater import StatusUpdater
from models.tts_queue import TTSStatus

logger = logging.getLogger(__name__)


class TTSService:
    """Main TTS service orchestrator."""

    def __init__(self) -> None:
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

        await self._interrupt_handler.connect()
        self._running = True

        async for doc in self._queue_listener.watch():
            if not self._running:
                break

            # Reset interrupt flag for new utterance
            await self._interrupt_handler.reset()

            # Process task (one at a time — no concurrent synthesis)
            await self._process_task(doc)

    async def _process_task(self, doc) -> None:
        """Process a single TTS task end-to-end."""
        logger.info(f"Processing task: {doc.id} | session: {doc.session_id}")

        try:
            await self._status_updater.set_status(doc.id, TTSStatus.PLAYING)

            audio_chunks = self._synthesizer.synthesize(doc.text)
            await self._player.play(audio_chunks, self._interrupt_handler.stop_event)

            if self._interrupt_handler.stop_event.is_set():
                await self._status_updater.set_status(doc.id, TTSStatus.INTERRUPTED)
                logger.info(f"Task interrupted: {doc.id}")
            else:
                await self._status_updater.set_status(doc.id, TTSStatus.COMPLETED)
                logger.info(f"Task completed: {doc.id}")

        except Exception as exc:
            logger.error(f"Task failed: {doc.id} — {exc}")
            try:
                await self._status_updater.set_status(
                    doc.id, TTSStatus.FAILED, str(exc)
                )
            except Exception as update_exc:
                logger.error(f"Failed to update status: {update_exc}")

    async def stop(self) -> None:
        """Stop TTS service gracefully."""
        logger.info("Stopping TTS Service...")
        self._running = False

        await self._interrupt_handler.close()
        await self._queue_listener.close()
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
