# app/stt/send_audio_to_realtime.py
from __future__ import annotations

class RealtimeAudioSender:
    """
    Skickar audio till Realtime och kan trigga commit.
    Kapslar RealtimeClient för enkel testning.
    """
    def __init__(self, rt_client) -> None:
        self.rt = rt_client

    async def append(self, chunk: bytes) -> None:
        await self.rt.append_pcm16le(chunk)

    async def commit(self) -> None:
        await self.rt.commit()
