# app/stt/send_text_to_frontend.py
from __future__ import annotations
from typing import Union, Dict, Any
from fastapi import WebSocket

class FrontendTextSender:
    """
    Skickar text/JSON till frontend över WebSocket.
    Tar emot antingen rå JSON-sträng eller Python-objekt.
    """
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def send(self, payload: Union[str, Dict[str, Any]]) -> None:
        if isinstance(payload, str):
            await self.ws.send_text(payload)
        else:
            await self.ws.send_json(payload)
