import logging
from typing import Dict, Any, Callable, Awaitable
from starlette.websockets import WebSocketState

log = logging.getLogger("stt")

async def on_rt_event(evt: dict, ws, send_json: bool, buffers, last_text: list):
    """
    Hanterar events från OpenAI Realtime och extraherar transcript.
    
    Args:
        evt: Event från Realtime
        ws: WebSocket-anslutning till frontend
        send_json: Om vi ska skicka JSON eller ren text
        buffers: Debug store buffers för session
        last_text: List med senaste text för att kunna uppdatera från utanför
    
    Returns:
        str: Delta text som ska skickas till frontend, eller None
    """
    t = evt.get("type")

    # (A) logga alltid eventtyp för felsökning (/debug/rt-events om ni har det)
    try:
        buffers.rt_events.append(str(t))
    except Exception:
        pass

    # (B) bubbla upp error/info till klienten (syns i browser-konsol)
    if t == "error":
        detail = evt.get("error", evt)
        if send_json and ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json({"type": "error", "reason": "realtime_error", "detail": detail})
        return None
    if t == "session.updated":
        if send_json and ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json({"type": "info", "msg": "realtime_connected_and_configured"})
        return None

    # (C) försök extrahera transcript från flera varianter
    transcript = None

    # 1) Klassisk Realtime-transkript (som repo 2 använder) - whisper-1 + server VAD
    if t == "conversation.item.input_audio_transcription.completed":
        transcript = (
            evt.get("transcript")
            or evt.get("item", {}).get("content", [{}])[0].get("transcript")
        )

    # 2) Alternativ nomenklatur: response.audio_transcript.delta/completed
    if not transcript and t in ("response.audio_transcript.delta", "response.audio_transcript.completed"):
        transcript = evt.get("transcript") or evt.get("text") or evt.get("delta")

    # 3) Sista fallback: response.output_text.delta (text-delning)
    if not transcript and t == "response.output_text.delta":
        delta_txt = evt.get("delta")
        if isinstance(delta_txt, str):
            transcript = (last_text[0] or "") + delta_txt

    if not isinstance(transcript, str) or not transcript:
        return None

    # (D) beräkna delta och returnera för skickning till frontend
    delta = transcript[len(last_text[0]):] if transcript.startswith(last_text[0]) else transcript
    
    if delta:
        buffers.openai_text.append(transcript)
        last_text[0] = transcript
        return delta
    
    return None
