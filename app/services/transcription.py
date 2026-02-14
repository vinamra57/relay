import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from app.config import DUMMY_MODE, ELEVENLABS_API_KEY

logger = logging.getLogger(__name__)

# Dummy transcript segments for debugging without API keys
DUMMY_SEGMENTS = [
    "Patient is a 45 year old male",
    "named John David Smith",
    "located at 742 Evergreen Terrace Springfield Illinois",
    "Chief complaint is chest pain radiating to left arm",
    "Started approximately 30 minutes ago",
    "Patient is alert and oriented and reports pain 8 out of 10",
    "Patient reports shortness of breath and diaphoresis",
    "Blood pressure is 160 over 95",
    "Heart rate 110 beats per minute",
    "Respiratory rate 22",
    "SPO2 94 percent on room air",
    "Blood glucose 145",
    "GCS 15 eyes 4 verbal 5 motor 6",
    "Patient history includes hypertension and diabetes type 2",
    "Patient reports no known allergies NKDA",
    "Administering aspirin 324 milligrams chewed",
    "Establishing IV access right antecubital",
    "Administering nitroglycerin 0.4 milligrams sublingual",
    "12 lead ECG shows ST elevation in leads V1 through V4",
    "Primary impression is STEMI",
    "Activating cardiac catheterization lab",
    "Transporting to Springfield General Hospital",
]


class TranscriptionService:
    """Manages ElevenLabs Scribe v2 Realtime WebSocket connection or dummy mode."""

    def __init__(
        self,
        on_partial: Callable[[str], Awaitable[None]],
        on_committed: Callable[[str], Awaitable[None]],
    ):
        self.on_partial = on_partial
        self.on_committed = on_committed
        self._ws = None
        self._listen_task = None
        self._dummy_task = None
        self._running = False

    async def start(self):
        """Start the transcription service."""
        self._running = True
        if DUMMY_MODE:
            logger.info("Starting transcription in DUMMY mode")
            self._dummy_task = asyncio.create_task(self._run_dummy())
        else:
            logger.info("Starting transcription with ElevenLabs Scribe v2 Realtime")
            await self._connect_elevenlabs()

    async def stop(self):
        """Stop the transcription service."""
        self._running = False
        if self._dummy_task and not self._dummy_task.done():
            self._dummy_task.cancel()
            try:
                await self._dummy_task
            except asyncio.CancelledError:
                pass
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
        """Send an audio chunk to ElevenLabs or ignore in dummy mode."""
        if DUMMY_MODE:
            return
        if self._ws:
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

        self._ws = await websockets.connect(uri, additional_headers=headers)
        self._listen_task = asyncio.create_task(self._listen_elevenlabs())

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
                    await self.on_partial(data.get("text", ""))
                elif msg_type in ("committed_transcript", "committed_transcript_with_timestamps"):
                    await self.on_committed(data.get("text", ""))
                elif msg_type == "session_started":
                    logger.info(f"ElevenLabs session started: {data.get('session_id')}")
                elif msg_type in ("error", "auth_error", "quota_exceeded", "rate_limited"):
                    logger.error(f"ElevenLabs error: {data}")
        except websockets.ConnectionClosed:
            logger.warning("ElevenLabs WebSocket connection closed")
        except Exception as e:
            logger.error(f"ElevenLabs listener error: {e}")

    async def _run_dummy(self):
        """Simulate transcription with pre-recorded segments."""
        try:
            await asyncio.sleep(1.0)  # Initial delay
            for segment in DUMMY_SEGMENTS:
                if not self._running:
                    break
                # Simulate partial transcript (word by word)
                words = segment.split()
                for i in range(1, len(words) + 1):
                    if not self._running:
                        break
                    partial = " ".join(words[:i])
                    await self.on_partial(partial)
                    await asyncio.sleep(0.15)

                # Committed transcript
                await self.on_committed(segment)
                await asyncio.sleep(1.5)  # Pause between segments
        except asyncio.CancelledError:
            pass
