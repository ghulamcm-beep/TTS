"""Unit tests: Interrupt handler stop event."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestInterruptHandler:
    """Tests for InterruptHandler NATS subscription."""

    @pytest.fixture
    def handler(self):
        from src.tts.interrupt_handler import InterruptHandler
        return InterruptHandler()

    def test_initial_stop_event_not_set(self, handler):
        assert not handler.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_handle_interrupt_sets_event(self, handler):
        msg = MagicMock()
        msg.data = b'{"session_id": "sess_001"}'
        await handler._handle_interrupt(msg)
        assert handler.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_reset_clears_event(self, handler):
        handler._stop_event.set()
        await handler.reset()
        assert not handler.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_handle_empty_payload(self, handler):
        msg = MagicMock()
        msg.data = b""
        await handler._handle_interrupt(msg)
        assert handler.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_close_without_connection(self, handler):
        # Should not raise if never connected
        await handler.close()

    @pytest.mark.asyncio
    async def test_close_with_connection(self, handler):
        mock_nc = AsyncMock()
        mock_nc.is_closed = False
        mock_sub = AsyncMock()
        handler._nc = mock_nc
        handler._subscription = mock_sub
        await handler.close()
        mock_sub.unsubscribe.assert_called_once()
        mock_nc.close.assert_called_once()
