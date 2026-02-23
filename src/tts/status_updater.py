"""MongoDB transcript update helper."""
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from .config import config

logger = logging.getLogger(__name__)


class TranscriptUpdater:
    """Updates interviews.transcripts documents after playback."""

    def __init__(self, mongo_client: AsyncIOMotorClient) -> None:
        self.db = mongo_client[config.mongodb_db]
        self.collection = self.db[config.transcripts_collection]

    async def mark_played(self, document_id: Any) -> None:
        """Set audio_url='played' to signal playback completion to main-agent."""
        await self.collection.update_one(
            {"_id": document_id},
            {"$set": {"audio_url": "played"}},
        )
        logger.info(f"Transcript marked as played: {document_id}")
