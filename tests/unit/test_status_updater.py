"""Unit tests: TranscriptUpdater MongoDB writes."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId


class TestTranscriptUpdater:
    """Tests for TranscriptUpdater MongoDB operations."""

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
        from src.tts.status_updater import TranscriptUpdater
        client, _ = mongo_client
        return TranscriptUpdater(client)

    @pytest.mark.asyncio
    async def test_mark_played_sets_audio_url(self, updater, mongo_client):
        """mark_played() sets audio_url='played' on the document."""
        _, collection = mongo_client
        collection.update_one = AsyncMock()

        await updater.mark_played("doc-001")

        call_args = collection.update_one.call_args
        update_doc = call_args[0][1]["$set"]
        assert update_doc["audio_url"] == "played"

    @pytest.mark.asyncio
    async def test_mark_played_uses_correct_document_id(self, updater, mongo_client):
        """mark_played() filters by _id."""
        _, collection = mongo_client
        collection.update_one = AsyncMock()

        await updater.mark_played("my-doc-id")

        call_args = collection.update_one.call_args
        filter_doc = call_args[0][0]
        assert filter_doc["_id"] == "my-doc-id"

    @pytest.mark.asyncio
    async def test_mark_played_accepts_objectid(self, updater, mongo_client):
        """mark_played() works with ObjectId as document id."""
        _, collection = mongo_client
        collection.update_one = AsyncMock()

        oid = ObjectId()
        await updater.mark_played(oid)

        call_args = collection.update_one.call_args
        filter_doc = call_args[0][0]
        assert filter_doc["_id"] == oid
