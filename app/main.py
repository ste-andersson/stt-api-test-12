from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.websockets import WebSocketState

from .config import settings
from .debug_store import store
from .realtime_client import OpenAIRealtimeClient
# NYTT: hjälp-funktioner för audio→Realtime
from .stt.send_audio_to_realtime import (
    init_audio_sender_state,
    start_commit_loop,
    stop_commit_loop,
    handle_audio_chunk,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stt")

app = FastAPI(title="stefan-api-test-7 – STT-backend (FastAPI + Realtime)")


# ----------------------- CORS -----------------------
origins = []
regex = None
for part in [p.strip() for p in settings.cors_origins.split(",") if p.strip()]:
    if "*" in part:
        # översätt *.lovable.app => regex
        escaped = re.escape(part).replace(r"\*\.", ".*")
        regex = rf"https://{escaped}" if part.startswith("*.") else rf"{escaped}"
    else:
        origins.append(part)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------- Models -----------------------
class ConfigOut(BaseModel):
    realtime_url: str
    transcribe_model: str
    input_language: str
    commit_interval_ms: int
    cors_origins: list[str]
    cors_regex: Optional[str]

class DebugListOut(BaseModel):
    session_id: str
    data: list

# --------------------- Endpoints --------------------
@app.get("/healthz")
async def healthz():
    return {"ok": True, "ts": time.time()}

@app.get("/config", response_model=ConfigOut)
async def get_config():
    return ConfigOut(
        realtime_url=settings.realtime_url,
        transcribe_model=settings.transcribe_model,
        input_language=settings.input_language,
        commit_interval_ms=settings.commit_interval_ms,
        cors_origins=origins,
        cors_regex=regex,
    )

@app.get("/debug/frontend-chunks", response_model=DebugListOut)
async def debug_frontend_chunks(session_id: str = Query(...), limit: int = Query(200, ge=1, le=1000)):
    buf = store.get_or_create(session_id)
    data = list(buf.frontend_chunks)[-limit:]
    return DebugListOut(session_id=session_id, data=data)

@app.get("/debug/openai-chunks", response_model=DebugListOut)
async def debug_openai_chunks(session_id: str = Query(...), limit: int = Query(200, ge=1, le=1000)):
    buf = store.get_or_create(session_id)
    data = list(buf.openai_chunks)[-limit:]
    return DebugListOut(session_id=session_id, data=data)

@app.get("/debug/openai-text", response_model=DebugListOut)
async def debug_openai_text(session_id: str = Query(...), limit: int = Query(200, ge=1, le=2000)):
    buf = store.get_or_create(session_id)
    data = list(buf.openai_text)[-limit:]
    return DebugListOut(session_id=session_id, data=data)

@app.get("/debug/frontend-text", response_model=DebugListOut)
async def debug_frontend_text(session_id: str = Query(...), limit: int = Query(200, ge=1, le=2000)):
    buf = store.get_or_create(session_id)
    data = list(buf.frontend_text)[-limit:]
    return DebugListOut(session_id=session_id, data=data)

@app.get("/debug/rt-events", response_model=DebugListOut)
async def debug_rt_events(session_id: str = Query(...), limit: int = Query(200, ge=1, le=2000)):
    buf = store.get_or_create(session_id)
    data = list(buf.rt_events)[-limit:]
    return DebugListOut(session_id=session_id, data=data)

@app.post("/debug/reset")
async def debug_reset(session_id: str | None = Query(None)):
    store.reset(session_id)
    return {"ok": True, "session_id": session_id}

# --------------------- WebSocket --------------------
@app.websocket("/ws/transcribe")
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
    
    # --- NYTT: ersätter lokala has_audio/last_audio_time + commit_loop ---
    audio_state = init_audio_sender_state(idle_timeout_s=2.0)
    commit_task = await start_commit_loop(
        state=audio_state,
        rt=rt,
        commit_interval_ms=settings.commit_interval_ms,
        logger=log,
    )
    # --------------------------------------------------------------------

    # Task: läs events från Realtime och skicka deltas till frontend
    async def on_rt_event(evt: dict):
        nonlocal last_text
        t = evt.get("type")

        try:
            buffers.rt_events.append(str(t))
        except Exception:
            pass

        if t == "error":
            detail = evt.get("error", evt)
            if send_json and ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "error", "reason": "realtime_error", "detail": detail})
            return
        if t == "session.updated":
            if send_json and ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "info", "msg": "realtime_connected_and_configured"})
            return

        transcript = None

        if t == "conversation.item.input_audio_transcription.completed":
            transcript = (
                evt.get("transcript")
                or evt.get("item", {}).get("content", [{}])[0].get("transcript")
            )

        if not transcript and t in ("response.audio_transcript.delta", "response.audio_transcript.completed"):
            transcript = evt.get("transcript") or evt.get("text") or evt.get("delta")

        if not transcript and t == "response.output_text.delta":
            delta_txt = evt.get("delta")
            if isinstance(delta_txt, str):
                transcript = (last_text or "") + delta_txt

        if not isinstance(transcript, str) or not transcript:
            return

        delta = transcript[len(last_text):] if transcript.startswith(last_text) else transcript

        if delta and ws.client_state == WebSocketState.CONNECTED:
            buffers.openai_text.append(transcript)
            
            is_final = t in (
                "conversation.item.input_audio_transcription.completed",
                "response.audio_transcript.completed",
            )
            
            if send_json:
                await ws.send_json({
                    "type": "stt.final" if is_final else "stt.partial",
                    "text": transcript
                })
            else:
                await ws.send_text(delta)
            buffers.frontend_text.append(delta)
            last_text = transcript

    rt_recv_task = asyncio.create_task(rt.recv_loop(on_rt_event))

    try:
        while ws.client_state == WebSocketState.CONNECTED:
            try:
                msg = await ws.receive()

                if "bytes" in msg and msg["bytes"] is not None:
                    chunk = msg["bytes"]
                    buffers.frontend_chunks.append(len(chunk))
                    try:
                        # --- NYTT: ersätter inline-append + stateuppdatering ---
                        await handle_audio_chunk(
                            state=audio_state,
                            rt=rt,
                            buffers=buffers,
                            chunk=chunk,
                            logger=log,
                        )
                        # --------------------------------------------------------
                    except Exception as e:
                        log.error("Fel när chunk skickades till Realtime: %s", e)
                        break
                elif "text" in msg and msg["text"] is not None:
                    if msg["text"] == "ping":
                        await ws.send_text("pong")
                    else:
                        pass
                else:
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
        # --- NYTT: stäng commit-loop via helper ---
        await stop_commit_loop(audio_state)
        # ------------------------------------------
        rt_recv_task.cancel()
        try:
            await rt.close()
        except Exception:
            pass
        try:
            # commit_task är redan stoppad, men det är ok att inkludera här för att behålla flödet
            await asyncio.gather(commit_task, rt_recv_task, return_exceptions=True)
        except Exception:
            pass
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass


# Alias route för /ws som använder samma logik som /ws/transcribe
@app.websocket("/ws")
async def ws_alias(ws: WebSocket):
    # Återanvänd exakt samma logik som i ws_transcribe
    await ws_transcribe(ws)
