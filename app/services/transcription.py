import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from app.config import ELEVENLABS_API_KEY

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Manages ElevenLabs Scribe v2 Realtime WebSocket for voice-to-text."""

    def __init__(
        self,
        on_partial: Callable[[str], Awaitable[None]],
        on_committed: Callable[[str], Awaitable[None]],
    ):
        self.on_partial = on_partial
        self.on_committed = on_committed
        self._ws = None
        self._listen_task = None
        self._running = False

    async def start(self):
        """Start the transcription service. Requires ELEVENLABS_API_KEY."""
        self._running = True
        if not ELEVENLABS_API_KEY:
            logger.warning("Transcription disabled: set ELEVENLABS_API_KEY for speech-to-text.")
            return
        logger.info("Starting transcription with ElevenLabs Scribe v2 Realtime")
        await self._connect_elevenlabs()

    async def stop(self):
        """Stop the transcription service."""
        self._running = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send_audio(self, audio_base64: str):
        """Send an audio chunk to ElevenLabs."""
        if not self._ws:
            return
        message = {
            "message_type": "input_audio_chunk",
            "audio_base_64": audio_base64,
            "commit": False,
            "sample_rate": 16000,
        }
        await self._ws.send(json.dumps(message))

    async def _connect_elevenlabs(self):
        """Connect to ElevenLabs Scribe v2 Realtime WebSocket."""
        uri = (
            "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
            "?model_id=scribe_v2_realtime"
            "&language_code=en"
            "&commit_strategy=vad"
            "&audio_format=pcm_16000"
        )
        headers = {"xi-api-key": ELEVENLABS_API_KEY}
        try:
            self._ws = await websockets.connect(uri, additional_headers=headers)
            self._listen_task = asyncio.create_task(self._listen_elevenlabs())
        except Exception as e:
            logger.error("ElevenLabs connection failed: %s", e)
            self._ws = None

    async def _listen_elevenlabs(self):
        """Listen for transcription events from ElevenLabs."""
        if self._ws is None:
            return
        try:
            async for raw_message in self._ws:
                if not self._running:
                    break
                data = json.loads(raw_message)
                msg_type = data.get("message_type", "")

                if msg_type == "partial_transcript":
                    text = data.get("text", "")
                    if text:
                        logger.info("Transcript (partial): %s", text[:80])
                    await self.on_partial(text)
                elif msg_type in ("committed_transcript", "committed_transcript_with_timestamps"):
                    text = data.get("text", "")
                    if text:
                        logger.info("Transcript (committed): %s", text[:80])
                    await self.on_committed(text)
                elif msg_type == "session_started":
                    logger.info("ElevenLabs session started: %s", data.get("session_id"))
                elif msg_type in ("error", "auth_error", "quota_exceeded", "rate_limited"):
                    logger.error("ElevenLabs error: %s", data)
                else:
                    logger.debug("ElevenLabs message: %s", msg_type)
        except websockets.ConnectionClosed:
            logger.warning("ElevenLabs WebSocket connection closed")
        except Exception as e:
            logger.error("ElevenLabs listener error: %s", e)
