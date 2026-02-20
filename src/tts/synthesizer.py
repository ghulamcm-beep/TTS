"""Piper TTS subprocess manager."""
import asyncio
import logging
from typing import AsyncGenerator, Optional

from .config import config

logger = logging.getLogger(__name__)


class PiperSynthesizer:
    """Manages Piper TTS subprocess lifecycle and audio synthesis."""

    def __init__(self) -> None:
        self._process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._restart_count = 0
        self._max_restarts = config.nats_max_reconnect_attempts  # reuse max retries

    async def _start_piper(self) -> asyncio.subprocess.Process:
        """Start Piper subprocess."""
        cmd = [
            config.piper_command,
            "--model", config.piper_model_path,
            "--output-raw",
        ]
        logger.info(f"Starting Piper: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return process

    async def _ensure_piper_running(self) -> None:
        """Ensure Piper is running, restart if crashed."""
        if self._process is None or self._process.returncode is not None:
            if self._restart_count >= self._max_restarts:
                raise RuntimeError(
                    f"Piper crashed {self._restart_count} times, giving up"
                )
            self._restart_count += 1
            logger.warning(f"Piper not running, restarting (attempt {self._restart_count})")
            self._process = await self._start_piper()

    async def synthesize(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Synthesize text to PCM audio chunks.

        Yields 4096-byte PCM chunks (s16le, 22050Hz, mono).
        Raises RuntimeError if Piper fails repeatedly.
        """
        async with self._lock:
            await self._ensure_piper_running()

            try:
                assert self._process is not None
                assert self._process.stdin is not None
                assert self._process.stdout is not None

                self._process.stdin.write(text.encode("utf-8") + b"\n")
                await self._process.stdin.drain()

                chunk_count = 0
                while True:
                    timeout = (
                        config.first_chunk_timeout
                        if chunk_count == 0
                        else config.next_chunk_timeout
                    )
                    try:
                        chunk = await asyncio.wait_for(
                            self._process.stdout.read(config.chunk_size),
                            timeout=timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Piper chunk timeout — ending synthesis")
                        break

                    if not chunk:
                        break

                    yield chunk
                    chunk_count += 1

                logger.info(f"Synthesis complete: {chunk_count} chunks")
                # Reset restart count on success
                self._restart_count = 0

            except Exception as exc:
                logger.error(f"Piper synthesis error: {exc}")
                if self._process and self._process.returncode is not None:
                    assert self._process.stderr is not None
                    stderr = await self._process.stderr.read()
                    logger.error(f"Piper stderr: {stderr.decode()}")
                    self._process = None  # force restart on next call
                raise

    async def close(self) -> None:
        """Clean up Piper subprocess."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()
            logger.info("Piper process terminated")
