"""Unit tests: Piper TTS synthesizer."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPiperSynthesizer:
    """Tests for PiperSynthesizer subprocess management."""

    @pytest.fixture
    def synthesizer(self):
        from src.tts.synthesizer import PiperSynthesizer
        return PiperSynthesizer()

    def test_initial_state(self, synthesizer):
        assert synthesizer._process is None
        assert synthesizer._restart_count == 0

    @pytest.mark.asyncio
    async def test_ensure_piper_starts_when_none(self, synthesizer):
        mock_process = MagicMock()
        mock_process.returncode = None
        with patch.object(synthesizer, "_start_piper", return_value=mock_process) as mock_start:
            await synthesizer._ensure_piper_running()
            mock_start.assert_called_once()
            assert synthesizer._process is mock_process
            assert synthesizer._restart_count == 1

    @pytest.mark.asyncio
    async def test_ensure_piper_restarts_on_crash(self, synthesizer):
        crashed_process = MagicMock()
        crashed_process.returncode = 1  # non-None means crashed
        synthesizer._process = crashed_process

        new_process = MagicMock()
        new_process.returncode = None
        with patch.object(synthesizer, "_start_piper", return_value=new_process):
            await synthesizer._ensure_piper_running()
            assert synthesizer._process is new_process

    @pytest.mark.asyncio
    async def test_max_restarts_raises(self, synthesizer):
        synthesizer._restart_count = synthesizer._max_restarts
        synthesizer._process = None

        with pytest.raises(RuntimeError, match="giving up"):
            await synthesizer._ensure_piper_running()

    @pytest.mark.asyncio
    async def test_close_terminates_process(self, synthesizer):
        mock_process = AsyncMock()
        mock_process.returncode = None
        synthesizer._process = mock_process
        await synthesizer.close()
        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_skips_if_already_terminated(self, synthesizer):
        mock_process = AsyncMock()
        mock_process.returncode = 0  # already terminated
        synthesizer._process = mock_process
        await synthesizer.close()
        mock_process.terminate.assert_not_called()
