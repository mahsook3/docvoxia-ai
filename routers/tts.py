"""
routers/tts.py
--------------
Text-to-Speech endpoints backed by Google Cloud TTS.

POST /synthesize   — convert text to audio, returns base64 MP3
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Lazy TTS client ───────────────────────────────────────────────────────────

_tts_client = None


def _get_tts_client():
    global _tts_client
    if _tts_client is None:
        from google.cloud import texttospeech
        _tts_client = texttospeech.TextToSpeechClient()
    return _tts_client


# ── Request / Response models ─────────────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    text: str
    language_code: str = "en-US"
    voice_name: Optional[str] = None      # e.g. "en-US-Journey-F"
    speaking_rate: float = 1.0
    pitch: float = 0.0


class SynthesizeResponse(BaseModel):
    audio_base64: str   # MP3 encoded as base64
    language_code: str
    voice_name: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/synthesize", response_model=SynthesizeResponse, tags=["TTS"])
async def synthesize_speech(body: SynthesizeRequest):
    """
    Synthesize text to speech using Google Cloud TTS.
    Returns MP3 audio as a base64-encoded string.
    """
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty.")

    try:
        from google.cloud import texttospeech

        client = _get_tts_client()

        synthesis_input = texttospeech.SynthesisInput(text=body.text)

        voice_params: dict = {"language_code": body.language_code}
        if body.voice_name:
            voice_params["name"] = body.voice_name

        voice = texttospeech.VoiceSelectionParams(**voice_params)
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=body.speaking_rate,
            pitch=body.pitch,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )

        audio_b64 = base64.b64encode(response.audio_content).decode("utf-8")
        resolved_voice = body.voice_name or f"{body.language_code}-Standard-A"

        return SynthesizeResponse(
            audio_base64=audio_b64,
            language_code=body.language_code,
            voice_name=resolved_voice,
        )

    except Exception as exc:
        logger.exception("TTS synthesis failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"TTS error: {exc}")
