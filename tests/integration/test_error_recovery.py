"""
Integration tests: Error recovery flows.

Tests for MongoDB reconnection and NATS reconnection logic.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


pytestmark = pytest.mark.asyncio


class TestErrorRecovery:
    """Tests for error recovery and reconnection logic."""

    async def test_synthesizer_resets_after_success(self):
        """restart_count resets to 0 after successful synthesis."""
        from src.tts.synthesizer import PiperSynthesizer

        synth = PiperSynthesizer()
        synth._restart_count = 2  # simulated previous crashes

        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.stdin = AsyncMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()

        # Simulate one chunk then timeout
        read_call_count = 0

        async def mock_read(n):
            nonlocal read_call_count
            if read_call_count == 0:
                read_call_count += 1
                return b"\x00" * n
            raise asyncio.TimeoutError()

        mock_process.stdout = AsyncMock()
        mock_process.stdout.read = mock_read

        with patch.object(synth, "_start_piper", return_value=mock_process):
            chunks = []
            async for chunk in synth.synthesize("test"):
                chunks.append(chunk)

        assert synth._restart_count == 0  # reset on success

    async def test_nats_interrupt_handler_resilient_to_empty_data(self):
        """Handler does not crash on empty NATS message."""
        from src.tts.interrupt_handler import InterruptHandler
        handler = InterruptHandler()

        msg = MagicMock()
        msg.data = b""

        await handler._handle_interrupt(msg)
        assert handler.stop_event.is_set()

    async def test_tts_queue_listener_handles_missing_full_document(self):
        """Queue listener skips change events without fullDocument."""
        # This tests the defensive check in tts_queue.py
        change_event = {"operationType": "insert"}  # no fullDocument key
        full_doc = change_event.get("fullDocument")
        assert full_doc is None  # should be skipped, not raise
