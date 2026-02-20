"""NATS subscriber for interrupt signals."""
import asyncio
import logging
from typing import Optional

import nats
from nats.aio.client import Client as NATSClient
from nats.aio.subscription import Subscription

from .config import config

logger = logging.getLogger(__name__)


class InterruptHandler:
    """Subscribes to NATS interrupt channel and exposes a stop event."""

    def __init__(self) -> None:
        self._nc: Optional[NATSClient] = None
        self._stop_event = asyncio.Event()
        self._subscription: Optional[Subscription] = None

    @property
    def stop_event(self) -> asyncio.Event:
        """Event that is set when an interrupt is received."""
        return self._stop_event

    async def connect(self) -> None:
        """Connect to NATS server and subscribe to interrupt subject."""
        self._nc = await nats.connect(
            config.nats_uri,
            max_reconnect_attempts=config.nats_max_reconnect_attempts,
            reconnect_time_wait=2,
            error_cb=self._error_cb,
            disconnected_cb=self._disconnected_cb,
            reconnected_cb=self._reconnected_cb,
        )
        self._subscription = await self._nc.subscribe(
            config.nats_interrupt_subject,
            cb=self._handle_interrupt,
        )
        logger.info(f"Subscribed to NATS subject: {config.nats_interrupt_subject}")

    async def _handle_interrupt(self, msg: nats.aio.msg.Msg) -> None:
        """Handle incoming interrupt message."""
        logger.info(f"Received interrupt signal: {msg.data.decode()}")
        self._stop_event.set()

    async def _error_cb(self, exc: Exception) -> None:
        logger.error(f"NATS error: {exc}")

    async def _disconnected_cb(self) -> None:
        logger.warning("NATS disconnected")

    async def _reconnected_cb(self) -> None:
        logger.info("NATS reconnected")

    async def reset(self) -> None:
        """Clear interrupt flag for the next utterance."""
        self._stop_event.clear()

    async def close(self) -> None:
        """Close NATS connection."""
        if self._subscription:
            await self._subscription.unsubscribe()
        if self._nc and not self._nc.is_closed:
            await self._nc.close()
            logger.info("NATS connection closed")
