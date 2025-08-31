# app/stt/realtime_client.py
from __future__ import annotations

import asyncio
import base64
import json
from typing import Optional, Dict

import websockets

class RealtimeClient:
    """
    Minimal OpenAI Realtime-klient över WebSocket.
    - append_pcm16le() kodar till base64 och skickar input_audio_buffer.append
    - commit() flushar bufferten
    - send_event() skickar valfri event
    - recv() returnerar rå-JSON-sträng från servern
    """
    def __init__(self, api_key: str, url: str, add_beta_header: bool):
        self.api_key = api_key
        self.url = url
        self.add_beta_header = add_beta_header
        self._conn: Optional[websockets.WebSocketClientProtocol] = None
        self._lock = asyncio.Lock()

    async def connect(self):
        headers: Dict[str, str] = {"Authorization": f"Bearer {self.api_key}"}
        if self.add_beta_header:
            headers["OpenAI-Beta"] = "realtime=v1"
        self._conn = await websockets.connect(self.url, extra_headers=headers)

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def append_pcm16le(self, pcm_bytes: bytes):
        if not self._conn:
            return
        b64 = base64.b64encode(pcm_bytes).decode("ascii")
        msg = {"type": "input_audio_buffer.append", "audio": b64}
        async with self._lock:
            await self._conn.send(json.dumps(msg))

    async def commit(self):
        if not self._conn:
            return
        msg = {"type": "input_audio_buffer.commit"}
        async with self._lock:
            await self._conn.send(json.dumps(msg))

    async def send_event(self, event: dict):
        if not self._conn:
            return
        async with self._lock:
            await self._conn.send(json.dumps(event))

    async def recv(self) -> Optional[str]:
        if not self._conn:
            return None
        try:
            return await self._conn.recv()
        except Exception:
            return None
