"""Tests for WebSocket streaming endpoint."""

import logging

logger = logging.getLogger(__name__)


def test_websocket_rejects_invalid_case(client):
    """Test WebSocket rejects connection for non-existent case."""
    with client.websocket_connect("/ws/stream/nonexistent-case-id") as ws:
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "not found" in data["message"].lower()


def test_websocket_connects_to_valid_case(client):
    """Test WebSocket accepts connection for valid case."""
    resp = client.post("/api/cases", json={})
    case_id = resp.json()["id"]

    with client.websocket_connect(f"/ws/stream/{case_id}") as ws:
        # Without ElevenLabs key, no transcription data is produced.
        # Verify connection works by sending end_call.
        ws.send_json({"type": "end_call"})


def test_websocket_end_call(client):
    """Test sending end_call message closes the connection."""
    resp = client.post("/api/cases", json={})
    case_id = resp.json()["id"]

    with client.websocket_connect(f"/ws/stream/{case_id}") as ws:
        ws.send_json({"type": "end_call"})


def test_websocket_audio_chunk_accepted(client):
    """Test sending audio chunk messages doesn't crash."""
    resp = client.post("/api/cases", json={})
    case_id = resp.json()["id"]

    with client.websocket_connect(f"/ws/stream/{case_id}") as ws:
        ws.send_json({"type": "audio_chunk", "data": "AAAA"})
        ws.send_json({"type": "end_call"})
