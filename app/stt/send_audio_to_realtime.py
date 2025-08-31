import asyncio
import logging
import time
from typing import Any

from ..config import settings

log = logging.getLogger("stt")

async def commit_loop(rt_client, has_audio_flag, last_audio_time):
    """
    Periodisk commit-loop för att få löpande partials från Realtime.
    
    Args:
        rt_client: OpenAI Realtime client
        has_audio_flag: Flagga som indikerar om vi har skickat ljud
        last_audio_time: Timestamp för senaste ljudet
    """
    try:
        while True:
            await asyncio.sleep(max(0.001, settings.commit_interval_ms / 1000))
            # Bara committa om vi har skickat ljud
            if has_audio_flag[0]:  # Använd list för att kunna uppdatera från utanför
                # Kontrollera om det har gått för lång tid sedan senaste ljudet
                if time.time() - last_audio_time[0] > 2.0:  # 2 sekunder timeout
                    has_audio_flag[0] = False
                    log.debug("Timeout - återställer has_audio flaggan")
                    continue
                
                try:
                    await rt_client.commit()
                except Exception as e:
                    # Hantera "buffer too small" fel mer elegant
                    if "buffer too small" in str(e) or "input_audio_buffer_commit_empty" in str(e):
                        log.debug("Buffer för liten, väntar på mer ljud: %s", e)
                        # Om buffern är helt tom, återställ has_audio flaggan
                        if "0.00ms of audio" in str(e):
                            has_audio_flag[0] = False
                        continue  # Fortsätt loopen istället för att bryta
                    else:
                        log.warning("Commit fel: %s", e)
                        break
    except asyncio.CancelledError:
        pass

def mark_audio_sent(has_audio_flag, last_audio_time):
    """
    Markerar att ljud har skickats till Realtime.
    
    Args:
        has_audio_flag: List med flagga för att kunna uppdatera från utanför
        last_audio_time: List med timestamp för att kunna uppdatera från utanför
    """
    has_audio_flag[0] = True
    last_audio_time[0] = time.time()
