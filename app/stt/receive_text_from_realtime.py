# app/stt/receive_text_from_realtime.py
from __future__ import annotations
from typing import AsyncIterator, Optional

class RealtimeTextReceiver:
    """
    Läser råa händelser från Realtime (JSON-strängar) och streamar dem vidare.
    """
    def __init__(self, rt_client) -> None:
        self.rt = rt_client

    async def stream_events(self) -> AsyncIterator[str]:
        while True:
            raw: Optional[str] = await self.rt.recv()
            if raw is None:
                break
            yield raw
