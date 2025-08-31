# app/stt/receive_audio_from_frontend.py
from __future__ import annotations
from typing import AsyncIterator
from fastapi import WebSocket

class FrontendAudioReceiver:
    """
    Tar emot binär PCM16LE (16 kHz mono) från frontend via WebSocket.
    Avkodar inte ljudet; exponerar bara bytes-chunks som iterator.
    """
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def read_chunks(self) -> AsyncIterator[bytes]:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
                yield data
            else:
                _ = msg.get("text")
