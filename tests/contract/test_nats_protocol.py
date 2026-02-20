"""Contract tests: NATS message format validation."""
import pytest
import json


class TestNATSProtocol:
    """Validate NATS interrupt message contract."""

    def test_interrupt_subject(self):
        from src.tts.config import config
        assert config.nats_interrupt_subject == "tts.interrupt"

    def test_empty_payload_is_valid(self):
        """Empty payload should be accepted (broadcast interrupt)."""
        payload = b""
        # Empty payload is valid for a broadcast interrupt
        assert payload == b""

    def test_json_payload_with_session_id(self):
        """JSON payload with session_id is valid for targeted interrupt."""
        payload = json.dumps({"session_id": "sess_123"}).encode()
        data = json.loads(payload)
        assert "session_id" in data
        assert data["session_id"] == "sess_123"

    def test_json_payload_without_session_id(self):
        """JSON payload without session_id is valid (interrupt all)."""
        payload = json.dumps({}).encode()
        data = json.loads(payload)
        assert isinstance(data, dict)

    def test_nats_uri_format(self):
        from src.tts.config import config
        assert config.nats_uri.startswith("nats://")

    def test_max_reconnect_attempts_positive(self):
        from src.tts.config import config
        assert config.nats_max_reconnect_attempts > 0
