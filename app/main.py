# app/main.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings  # använder samma Settings som idag
from app.endpoints.health import router as health_router
from app.endpoints.stt_ws import router as stt_router

app = FastAPI(title="Live Transcription Backend")

# CORS – behåller kommaseparerad sträng enligt ditt format
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health_router)
app.include_router(stt_router)
