# app/endpoints/health.py
from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import JSONResponse

from app.config import settings

router = APIRouter()

@router.get("/healthz")
async def healthz():
    ok = bool(settings.openai_api_key and settings.realtime_url)
    return JSONResponse({"ok": ok})
