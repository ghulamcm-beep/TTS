"""MongoDB status update helper."""
import logging
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

from .config import config
from models.tts_queue import TTSStatus

logger = logging.getLogger(__name__)


class StatusUpdater:
    """Updates TTS queue document status in MongoDB."""

    def __init__(self, mongo_client: AsyncIOMotorClient) -> None:
        self.db = mongo_client[config.mongodb_db]
        self.collection = self.db[config.tts_queue_collection]

    async def set_status(
        self,
        document_id: str,
        status: TTSStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """Update document status with appropriate timestamp."""
        now = datetime.now(timezone.utc)
        update_fields: dict = {"status": status.value}

        if status == TTSStatus.PLAYING:
            update_fields["started_at"] = now
        elif status == TTSStatus.COMPLETED:
            update_fields["completed_at"] = now
        elif status == TTSStatus.INTERRUPTED:
            update_fields["interrupted_at"] = now
        elif status == TTSStatus.FAILED:
            update_fields["error_message"] = error_message

        await self.collection.update_one(
            {"_id": document_id},
            {"$set": update_fields},
        )
        logger.info(
            "Status updated",
            extra={"document_id": document_id, "status": status.value},
        )
