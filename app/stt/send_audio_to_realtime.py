from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional


def init_audio_sender_state(*, idle_timeout_s: float = 2.0) -> Dict[str, Any]:
    """
    Minimal statecontainer som motsvarar:
      has_audio = False
      last_audio_time = 0
      commit_task = None
    """
    return {
        "has_audio": False,
        "last_audio_time": 0.0,
        "idle_timeout_s": float(idle_timeout_s),
        "commit_task": None,  # type: Optional[asyncio.Task]
    }


async def start_commit_loop(*, state: Dict[str, Any], rt, commit_interval_ms: int, logger) -> asyncio.Task:
    """
    Periodisk commit för att få löpande partials.
    Beteende matchar main.py:
      - sover max(0.001, commit_interval_ms/1000)
      - commitar endast om has_audio är True
      - om inaktiv längre än idle_timeout_s → has_audio = False
      - hanterar 'buffer too small'/'input_audio_buffer_commit_empty' mjukt
      - annars varnar och bryter loopen
    """
    async def _commit_loop():
        try:
            while True:
                await asyncio.sleep(max(0.001, commit_interval_ms / 1000))
                if state["has_audio"]:
                    if time.time() - state["last_audio_time"] > state["idle_timeout_s"]:
                        state["has_audio"] = False
                        logger.debug("Timeout - återställer has_audio flaggan")
                        continue
                    try:
                        await rt.commit()
                    except Exception as e:
                        msg = str(e)
                        if ("buffer too small" in msg) or ("input_audio_buffer_commit_empty" in msg):
                            logger.debug("Buffer för liten, väntar på mer ljud: %s", e)
                            if "0.00ms of audio" in msg:
                                state["has_audio"] = False
                            continue
                        else:
                            logger.warning("Commit fel: %s", e)
                            break
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(_commit_loop())
    state["commit_task"] = task
    return task


async def stop_commit_loop(state: Dict[str, Any]) -> None:
    """Avsluta commit-loopen om den körs."""
    task: Optional[asyncio.Task] = state.get("commit_task")
    if not task:
        return
    try:
        task.cancel()
    finally:
        try:
            await asyncio.gather(task, return_exceptions=True)
        except Exception:
            pass


async def handle_audio_chunk(*, state: Dict[str, Any], rt, buffers, chunk: bytes, logger) -> None:
    """
    Skickar chunk till Realtime och uppdaterar:
      - buffers.openai_chunks.append(len(chunk))
      - state['has_audio'] = True
      - state['last_audio_time'] = time.time()
    """
    await rt.send_audio_chunk(chunk)
    try:
        buffers.openai_chunks.append(len(chunk))
    except Exception:
        pass
    state["has_audio"] = True
    state["last_audio_time"] = time.time()
