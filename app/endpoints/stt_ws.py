import asyncio
import logging
import os
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from ..config import settings
from ..debug_store import store
from ..realtime_client import OpenAIRealtimeClient
from ..stt.receive_audio_from_frontend import receive_audio_chunk, handle_text_message
from ..stt.send_audio_to_realtime import commit_loop, mark_audio_sent
from ..stt.receive_text_from_realtime import on_rt_event
from ..stt.send_text_to_frontend import send_text_to_frontend, is_final_transcript

log = logging.getLogger("stt")

router = APIRouter()

@router.websocket("/ws/transcribe")
async def ws_transcribe(ws: WebSocket):
    await ws.accept()
    
    # A är default: JSON, B som fallback: ren text
    mode = (ws.query_params.get("mode") or os.getenv("WS_DEFAULT_MODE", "json")).lower()
    send_json = (mode == "json")
    
    session_id = store.new_session()
    
    # Skicka "ready" meddelande för kompatibilitet med frontend
    if send_json:
        await ws.send_json({
            "type": "ready",
            "audio_in": {"encoding": "pcm16", "sample_rate_hz": 16000, "channels": 1},
            "audio_out": {"mimetype": "audio/mpeg"},
        })
        await ws.send_json({"type": "session.started", "session_id": session_id})

    # Setup klient mot OpenAI/Azure Realtime
    rt = OpenAIRealtimeClient(
        url=settings.realtime_url,
        api_key=settings.openai_api_key,
        transcribe_model=settings.transcribe_model,
        language=settings.input_language,
        add_beta_header=settings.add_beta_header,
    )
    
    try:
        await rt.connect()
    except Exception as e:
        if send_json and ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json({"type": "error", "reason": "realtime_connect_failed", "detail": str(e)})
        return
    else:
        if send_json and ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json({"type": "info", "msg": "realtime_connected"})

    buffers = store.get_or_create(session_id)

    # Hålla senaste text för enkel diff
    last_text = ""
    
    # Flagga för att veta om vi har skickat ljud
    has_audio = False
    last_audio_time = 0  # Timestamp för senaste ljud

    # Task: läs events från Realtime och skicka deltas till frontend
    async def handle_rt_event(evt: dict):
        nonlocal last_text
        delta = await on_rt_event(evt, ws, send_json, buffers, [last_text])
        
        if delta:
            transcript = last_text + delta
            is_final = is_final_transcript(evt.get("type"))
            await send_text_to_frontend(ws, delta, transcript, is_final, send_json, buffers)
            last_text = transcript

    rt_recv_task = asyncio.create_task(rt.recv_loop(handle_rt_event))

    # Periodisk commit för att få löpande partials
    has_audio_flag = [has_audio]
    last_audio_time_list = [last_audio_time]
    
    async def local_commit_loop():
        await commit_loop(rt, has_audio_flag, last_audio_time_list)

    commit_task = asyncio.create_task(local_commit_loop())

    try:
        while ws.client_state == WebSocketState.CONNECTED:
            try:
                msg = await ws.receive()

                if "bytes" in msg and msg["bytes"] is not None:
                    success = await receive_audio_chunk(msg, buffers, rt)
                    if success:
                        mark_audio_sent(has_audio_flag, last_audio_time_list)
                    else:
                        break
                elif "text" in msg and msg["text"] is not None:
                    if handle_text_message(msg, ws):
                        if msg["text"] == "ping":
                            await ws.send_text("pong")
                    else:
                        # okänt format
                        pass
                else:
                    # okänt format
                    pass

            except WebSocketDisconnect:
                log.info("WebSocket stängd: %s", session_id)
                break
            except RuntimeError as e:
                log.info("WS disconnect during receive(): %s", e)
                break
            except Exception as e:
                log.error("WebSocket fel: %s", e)
                break
    finally:
        commit_task.cancel()
        rt_recv_task.cancel()
        try:
            await rt.close()
        except Exception:
            pass
        try:
            await asyncio.gather(commit_task, rt_recv_task, return_exceptions=True)
        except Exception:
            pass
        # Stäng WebSocket bara om den inte redan är stängd
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass

# Alias route för /ws som använder samma logik som /ws/transcribe
@router.websocket("/ws")
async def ws_alias(ws: WebSocket):
    # Återanvänd exakt samma logik som i ws_transcribe
    await ws_transcribe(ws)
