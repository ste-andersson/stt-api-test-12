import logging
from typing import Dict, Any

log = logging.getLogger("stt")

async def receive_audio_chunk(msg: Dict[str, Any], buffers, rt_client):
    """
    Hanterar mottagning av ljudchunks från frontend WebSocket.
    
    Args:
        msg: WebSocket-meddelandet från frontend
        buffers: Debug store buffers för session
        rt_client: OpenAI Realtime client
    
    Returns:
        bool: True om ljudchunk hanterades framgångsrikt, False annars
    """
    if "bytes" in msg and msg["bytes"] is not None:
        chunk = msg["bytes"]
        buffers.frontend_chunks.append(len(chunk))
        try:
            await rt_client.send_audio_chunk(chunk)
            buffers.openai_chunks.append(len(chunk))
            return True
        except Exception as e:
            log.error("Fel när chunk skickades till Realtime: %s", e)
            return False
    return False

def handle_text_message(msg: Dict[str, Any], ws):
    """
    Hanterar text-meddelanden från frontend (ping/pong etc).
    
    Args:
        msg: WebSocket-meddelandet från frontend
        ws: WebSocket-anslutning till frontend
    
    Returns:
        bool: True om meddelandet hanterades, False annars
    """
    if "text" in msg and msg["text"] is not None:
        # Tillåt ping/ctrl meddelanden som sträng
        if msg["text"] == "ping":
            return True  # Hanteras av anropande kod
        else:
            # ignoreras
            return True
    return False
