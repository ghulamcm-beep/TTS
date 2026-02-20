"""Unit tests: Status updater MongoDB writes."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


class TestStatusUpdater:
    """Tests for StatusUpdater MongoDB operations."""

    @pytest.fixture
    def mongo_client(self):
        client = MagicMock()
        collection = AsyncMock()
        db = MagicMock()
        db.__getitem__ = MagicMock(return_value=collection)
        client.__getitem__ = MagicMock(return_value=db)
        return client, collection

    @pytest.fixture
    def updater(self, mongo_client):
        from src.tts.status_updater import StatusUpdater
        client, _ = mongo_client
        return StatusUpdater(client)

    @pytest.mark.asyncio
    async def test_set_status_playing_sets_started_at(self, updater, mongo_client):
        from models.tts_queue import TTSStatus
        _, collection = mongo_client
        collection.update_one = AsyncMock()

        await updater.set_status("doc-001", TTSStatus.PLAYING)

        call_args = collection.update_one.call_args
        update_doc = call_args[0][1]["$set"]
        assert update_doc["status"] == "playing"
        assert "started_at" in update_doc

    @pytest.mark.asyncio
    async def test_set_status_completed_sets_completed_at(self, updater, mongo_client):
        from models.tts_queue import TTSStatus
        _, collection = mongo_client
        collection.update_one = AsyncMock()

        await updater.set_status("doc-001", TTSStatus.COMPLETED)

        call_args = collection.update_one.call_args
        update_doc = call_args[0][1]["$set"]
        assert update_doc["status"] == "completed"
        assert "completed_at" in update_doc

    @pytest.mark.asyncio
    async def test_set_status_interrupted_sets_interrupted_at(self, updater, mongo_client):
        from models.tts_queue import TTSStatus
        _, collection = mongo_client
        collection.update_one = AsyncMock()

        await updater.set_status("doc-001", TTSStatus.INTERRUPTED)

        call_args = collection.update_one.call_args
        update_doc = call_args[0][1]["$set"]
        assert update_doc["status"] == "interrupted"
        assert "interrupted_at" in update_doc

    @pytest.mark.asyncio
    async def test_set_status_failed_sets_error_message(self, updater, mongo_client):
        from models.tts_queue import TTSStatus
        _, collection = mongo_client
        collection.update_one = AsyncMock()

        await updater.set_status("doc-001", TTSStatus.FAILED, "Piper crashed")

        call_args = collection.update_one.call_args
        update_doc = call_args[0][1]["$set"]
        assert update_doc["status"] == "failed"
        assert update_doc["error_message"] == "Piper crashed"

    @pytest.mark.asyncio
    async def test_update_uses_correct_document_id(self, updater, mongo_client):
        from models.tts_queue import TTSStatus
        _, collection = mongo_client
        collection.update_one = AsyncMock()

        await updater.set_status("my-doc-id", TTSStatus.PLAYING)

        call_args = collection.update_one.call_args
        filter_doc = call_args[0][0]
        assert filter_doc["_id"] == "my-doc-id"
