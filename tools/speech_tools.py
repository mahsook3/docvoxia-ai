"""
tools/speech_tools.py
----------------------
ADK-compatible tool wrapping Google Cloud Text-to-Speech API.

Exposed tool:
  - synthesize_speech : convert text to MP3 audio (base64-encoded)
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy TTS client
_tts_client = None


def _get_client():
    global _tts_client
    if _tts_client is None:
        from google.cloud import texttospeech
        _tts_client = texttospeech.TextToSpeechClient()
    return _tts_client


def synthesize_speech(
    text: str,
    language_code: str = "en-US",
    voice_name: Optional[str] = None,
    speaking_rate: float = 1.0,
    pitch: float = 0.0,
) -> dict:
    """
    Convert text to speech using Google Cloud Text-to-Speech and return MP3 audio.

    Args:
        text:          The text to synthesize. Must not be empty.
        language_code: BCP-47 language code (e.g. "en-US", "ta-IN", "hi-IN").
        voice_name:    Optional specific voice name (e.g. "en-US-Journey-F").
                       If omitted, the API picks the best standard voice for
                       the given language_code.
        speaking_rate: Speed of speech. 1.0 is normal; range 0.25–4.0.
        pitch:         Voice pitch in semitones. 0.0 is default; range -20.0–20.0.

    Returns:
        Dict with keys:
          - "audio_base64"   : str  — MP3 audio encoded as base64
          - "language_code"  : str  — language code used
          - "voice_name"     : str  — voice name used
          - "character_count": int  — number of characters synthesized
    """
    if not text or not text.strip():
        return {
            "audio_base64":    "",
            "language_code":   language_code,
            "voice_name":      voice_name or "",
            "character_count": 0,
            "error":           "text must not be empty",
        }

    try:
        from google.cloud import texttospeech

        client          = _get_client()
        synthesis_input = texttospeech.SynthesisInput(text=text)

        voice_params: dict = {"language_code": language_code}
        if voice_name:
            voice_params["name"] = voice_name

        voice        = texttospeech.VoiceSelectionParams(**voice_params)
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate,
            pitch=pitch,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )

        audio_b64      = base64.b64encode(response.audio_content).decode("utf-8")
        resolved_voice = voice_name or f"{language_code}-Standard-A"

        return {
            "audio_base64":    audio_b64,
            "language_code":   language_code,
            "voice_name":      resolved_voice,
            "character_count": len(text),
        }

    except Exception as exc:
        logger.exception("TTS synthesis failed: %s", exc)
        return {
            "audio_base64":    "",
            "language_code":   language_code,
            "voice_name":      voice_name or "",
            "character_count": 0,
            "error":           str(exc),
        }