"""MongoDB change stream listener for TTS queue."""
import asyncio
import logging
from typing import AsyncGenerator, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from .config import config
from models.tts_queue import TTSQueueDocument, TTSStatus

logger = logging.getLogger(__name__)


class TTSQueueListener:
    """Watches MongoDB tts_queue for new documents via change streams."""

    def __init__(self, mongo_client: AsyncIOMotorClient) -> None:
        self.db = mongo_client[config.mongodb_db]
        self.collection = self.db[config.tts_queue_collection]
        self._change_stream = None
        self._closed = False

    async def watch(self) -> AsyncGenerator[TTSQueueDocument, None]:
        """
        Watch for new TTS queue documents.

        Yields parsed TTSQueueDocument on insert with status=pending.
        Reconnects automatically on transient errors.
        """
        pipeline = [{"$match": {"operationType": "insert"}}]
        retry_delay = 1.0
        max_retries = config.mongo_max_retries

        for attempt in range(max_retries):
            try:
                self._change_stream = self.collection.watch(
                    pipeline,
                    full_document="updateLookup",
                )
                logger.info("Watching MongoDB tts_queue for new documents")
                retry_delay = 1.0  # reset on success

                async for change in self._change_stream:
                    if self._closed:
                        return
                    try:
                        full_doc = change.get("fullDocument") or change.get("fullDocument")
                        if not full_doc:
                            continue
                        doc = TTSQueueDocument.model_validate(full_doc)
                        if doc.status == TTSStatus.PENDING:
                            logger.info(
                                f"New TTS task: {doc.id} (session: {doc.session_id})"
                            )
                            yield doc
                    except Exception as exc:
                        logger.error(f"Error parsing queue document: {exc}")

            except Exception as exc:
                if self._closed:
                    return
                logger.warning(
                    f"MongoDB change stream error (attempt {attempt + 1}/{max_retries}): {exc}"
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)  # exponential backoff

        logger.error("Max MongoDB reconnection attempts reached")

    async def close(self) -> None:
        """Close change stream."""
        self._closed = True
        if self._change_stream:
            await self._change_stream.close()
            logger.info("MongoDB change stream closed")
