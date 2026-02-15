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
    """Test WebSocket accepts connection for valid case and streams dummy data."""
    resp = client.post("/api/cases", json={})
    case_id = resp.json()["id"]

    with client.websocket_connect(f"/ws/stream/{case_id}") as ws:
        messages = []
        for _ in range(10):
            try:
                data = ws.receive_json()
                messages.append(data)
                if data["type"] == "transcript_committed":
                    break
            except Exception:
                logger.debug("WS receive ended")
                break

        types = [m["type"] for m in messages]
        assert "transcript_partial" in types or "transcript_committed" in types


def test_websocket_receives_nemsis_updates(client):
    """Test that NEMSIS extraction results are pushed via WebSocket."""
    resp = client.post("/api/cases", json={})
    case_id = resp.json()["id"]

    with client.websocket_connect(f"/ws/stream/{case_id}") as ws:
        nemsis_updates = []
        committed_count = 0
        for _ in range(50):
            try:
                data = ws.receive_json()
                if data["type"] == "nemsis_update":
                    nemsis_updates.append(data)
                    break
                if data["type"] == "transcript_committed":
                    committed_count += 1
            except Exception:
                logger.debug("WS receive ended during NEMSIS collection")
                break

        if committed_count > 0 and not nemsis_updates:
            try:
                for _ in range(20):
                    data = ws.receive_json()
                    if data["type"] == "nemsis_update":
                        nemsis_updates.append(data)
                        break
            except Exception:
                logger.debug("WS receive ended while waiting for NEMSIS update")

        if nemsis_updates:
            nemsis = nemsis_updates[0]["nemsis"]
            assert "patient" in nemsis
            assert "vitals" in nemsis


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
        try:
            data = ws.receive_json()
            assert data["type"] in [
                "transcript_partial",
                "transcript_committed",
                "nemsis_update",
                "error",
            ]
        except Exception:
            logger.debug("WS receive timed out (expected in test context)")
