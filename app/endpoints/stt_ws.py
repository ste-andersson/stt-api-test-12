# app/endpoints/stt_ws.py
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.stt.receive_audio_from_frontend import FrontendAudioReceiver
from app.stt.send_audio_to_realtime import RealtimeAudioSender
from app.stt.receive_text_from_realtime import RealtimeTextReceiver
from app.stt.send_text_to_frontend import FrontendTextSender
from app.stt.realtime_client import RealtimeClient

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

class CommitScheduler:
    """
    Periodisk commit enligt settings.commit_interval_ms.
    Via .poke() kan man forcera en commit tidigare; annars commit på timeout.
    """
    def __init__(self, sender: RealtimeAudioSender, interval_ms: int):
        self._sender = sender
        self._interval = max(50, int(interval_ms)) / 1000.0
        self._event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    def start(self):
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        try:
            while True:
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    pass
                self._event.clear()
                await self._sender.commit()
        except asyncio.CancelledError:
            pass

    async def stop(self):
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def poke(self):
        if not self._event.is_set():
            self._event.set()

@router.websocket("/ws")
async def ws_handler(client_ws: WebSocket):
    await client_ws.accept()

    # Skicka “ready” till frontend som handshake
    await client_ws.send_json({"type": "ready"})

    # Initiera klient mot OpenAI Realtime
    rt_client = RealtimeClient(
        api_key=settings.openai_api_key,
        url=settings.realtime_url,
        add_beta_header=settings.add_beta_header,
    )

    await rt_client.connect()

    # Start-kontext: instruera texttranskription på valt språk (valfritt men praktiskt)
    await rt_client.send_event(
        {
            "type": "response.create",
            "response": {
                "modalities": ["text"],
                "instructions": f"Transcribe in {settings.input_language}",
            },
        }
    )

    # Moduler (små och testbara)
    audio_in = FrontendAudioReceiver(client_ws)
    text_out = FrontendTextSender(client_ws)
    audio_up = RealtimeAudioSender(rt_client)
    text_in = RealtimeTextReceiver(rt_client)

    # Commit-scheduler (periodisk fallback)
    scheduler = CommitScheduler(audio_up, settings.commit_interval_ms)
    scheduler.start()

    # Läsa Realtime → skicka till frontend
    async def upstream_reader():
        async for raw in text_in.stream_events():
            # Vidarebefordra rå-JSON (frontend i Lovable kan tolka den)
            await text_out.send(raw)

    upstream_task = asyncio.create_task(upstream_reader())

    try:
        # Huvudloop: ta emot audio från frontend och skicka upp
        async for chunk in audio_in.read_chunks():
            await audio_up.append(chunk)
            # Låt periodisk commit sköta resten
    except WebSocketDisconnect:
        pass
    finally:
        upstream_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await upstream_task
        # stängning
        await rt_client.close()
        await client_ws.close()
