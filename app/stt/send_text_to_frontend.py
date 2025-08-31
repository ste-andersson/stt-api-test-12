import logging
from typing import Dict, Any
from starlette.websockets import WebSocketState

log = logging.getLogger("stt")

async def send_text_to_frontend(ws, delta: str, transcript: str, is_final: bool, 
                               send_json: bool, buffers):
    """
    Skickar text till frontend via WebSocket.
    
    Args:
        ws: WebSocket-anslutning till frontend
        delta: Delta text som ska skickas
        transcript: Hela transcriptet
        is_final: Om detta är final eller partial transcript
        send_json: Om vi ska skicka JSON eller ren text
        buffers: Debug store buffers för session
    """
    if delta and ws.client_state == WebSocketState.CONNECTED:
        # Bestäm om detta är final eller partial transcript
        if send_json:
            await ws.send_json({
                "type": "stt.final" if is_final else "stt.partial",
                "text": transcript
            })
        else:
            await ws.send_text(delta)  # fallback: ren text
        
        buffers.frontend_text.append(delta)

def is_final_transcript(event_type: str) -> bool:
    """
    Bestämmer om en event-typ representerar final transcript.
    
    Args:
        event_type: Typ av event från Realtime
    
    Returns:
        bool: True om final transcript, False annars
    """
    return event_type in (
        "conversation.item.input_audio_transcription.completed",
        "response.audio_transcript.completed",
    )
