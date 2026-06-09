"""
routers/asr.py
--------------
ASR (Automatic Speech Recognition) endpoints.

POST /transcribe        — transcribe an uploaded audio file
POST /transcribe-bytes  — transcribe raw audio bytes (base64)
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from utils.speech_transcriber import SpeechTranscriber

logger = logging.getLogger(__name__)
router = APIRouter()

# One shared transcriber instance (reuses gRPC channel)
_transcriber = SpeechTranscriber()


# ── Request / Response models ─────────────────────────────────────────────────

class TranscribeBytesRequest(BaseModel):
    audio_base64: str
    filename: Optional[str] = ""
    min_speakers: int = 1
    max_speakers: int = 6


class TranscriptionResponse(BaseModel):
    transcript: str
    utterances: list
    detected_languages: list
    speakers: list
    speaker_count: int
    filename: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/transcribe", response_model=TranscriptionResponse, tags=["ASR"])
async def transcribe_audio(
    file: UploadFile = File(...),
    min_speakers: int = Form(1),
    max_speakers: int = Form(6),
):
    """
    Transcribe an uploaded audio file (any format — auto-detected).
    Supports speaker diarization and automatic language detection (Chirp 3).
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        result = _transcriber.transcribe(
            audio_bytes,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            filename=file.filename or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        logger.exception("Transcription failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return TranscriptionResponse(**result.to_dict())


@router.post("/transcribe-bytes", response_model=TranscriptionResponse, tags=["ASR"])
async def transcribe_bytes(body: TranscribeBytesRequest):
    """
    Transcribe raw audio provided as a base64-encoded string.
    Useful for browser/mobile clients that send audio blobs directly.
    """
    try:
        audio_bytes = base64.b64decode(body.audio_base64)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid base64 audio data.")

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Decoded audio is empty.")

    try:
        result = _transcriber.transcribe(
            audio_bytes,
            min_speakers=body.min_speakers,
            max_speakers=body.max_speakers,
            filename=body.filename or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        logger.exception("Transcription failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return TranscriptionResponse(**result.to_dict())
