"""
utils/speech_transcriber.py

Google Cloud Speech-to-Text v2 (Chirp 3) transcription utility.

Features:
  - Automatic language detection  (language_codes=["auto"])
  - Speaker diarization           (RecognitionFeatures.diarization_config)
  - Auto audio format detection   (AutoDetectDecodingConfig)

Usage:
    from utils.speech_transcriber import SpeechTranscriber, TranscriptionResult

    transcriber = SpeechTranscriber()
    result = transcriber.transcribe(audio_bytes, min_speakers=1, max_speakers=6)
"""

from dataclasses import dataclass, field
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
from google.api_core.client_options import ClientOptions

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ID = "docvoxia"
LOCATION   = "asia-south1"

# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Utterance:
    """A single speaker turn."""
    speaker: str
    text: str


@dataclass
class TranscriptionResult:
    """Full result returned by SpeechTranscriber.transcribe()."""
    transcript: str
    utterances: list[Utterance]
    detected_languages: list[str]
    speakers: list[str]
    speaker_count: int
    filename: str = ""

    def to_dict(self) -> dict:
        return {
            "transcript":          self.transcript,
            "utterances":          [{"speaker": u.speaker, "text": u.text} for u in self.utterances],
            "detected_languages":  self.detected_languages,
            "speakers":            self.speakers,
            "speaker_count":       self.speaker_count,
            "filename":            self.filename,
        }


# ── Transcriber ───────────────────────────────────────────────────────────────

class SpeechTranscriber:
    """
    Thin wrapper around the Google Cloud Speech-to-Text v2 client.

    One instance is enough for the lifetime of the application — the underlying
    gRPC channel is reused across calls.
    """

    def __init__(self, project_id: str = PROJECT_ID, location: str = LOCATION) -> None:
        self.project_id = project_id
        self.location   = location
        self.recognizer = f"projects/{project_id}/locations/{location}/recognizers/_"

        self._client = SpeechClient(
            client_options=ClientOptions(
                api_endpoint=f"{location}-speech.googleapis.com"
            )
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        min_speakers: int = 1,
        max_speakers: int = 6,
        filename: str = "",
    ) -> TranscriptionResult:
        """
        Transcribe raw audio bytes.

        Args:
            audio_bytes:  Raw audio content (any format — auto-detected).
            min_speakers: Minimum number of speakers for diarization (≥ 1).
            max_speakers: Maximum number of speakers for diarization (≤ 6).
            filename:     Optional original filename, passed through to the result.

        Returns:
            TranscriptionResult with full transcript, per-speaker utterances,
            detected language(s), and speaker metadata.

        Raises:
            ValueError:   If min_speakers > max_speakers or audio_bytes is empty.
            RuntimeError: If the Speech API returns an error.
        """
        self._validate(audio_bytes, min_speakers, max_speakers)

        config  = self._build_config(min_speakers, max_speakers)
        request = cloud_speech.RecognizeRequest(
            recognizer=self.recognizer,
            config=config,
            content=audio_bytes,
        )

        try:
            response = self._client.recognize(request=request)
        except Exception as exc:
            raise RuntimeError(f"Speech API error: {exc}") from exc

        return self._parse_response(response, filename)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _validate(audio_bytes: bytes, min_speakers: int, max_speakers: int) -> None:
        if not audio_bytes:
            raise ValueError("audio_bytes must not be empty.")
        if min_speakers > max_speakers:
            raise ValueError("min_speakers cannot exceed max_speakers.")

    @staticmethod
    def _build_config(min_speakers: int, max_speakers: int) -> cloud_speech.RecognitionConfig:
        return cloud_speech.RecognitionConfig(
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=["auto"],   # Chirp 3 automatic language detection
            model="chirp_3",
            features=cloud_speech.RecognitionFeatures(
                # Diarization lives inside RecognitionFeatures (v2 API)
                diarization_config=cloud_speech.SpeakerDiarizationConfig(
                    min_speaker_count=min_speakers,
                    max_speaker_count=max_speakers,
                ),
                enable_automatic_punctuation=True,
                enable_word_time_offsets=True,
            ),
        )

    @staticmethod
    def _parse_response(
        response: cloud_speech.RecognizeResponse,
        filename: str,
    ) -> TranscriptionResult:
        if not response.results:
            return TranscriptionResult(
                transcript="",
                utterances=[],
                detected_languages=[],
                speakers=[],
                speaker_count=0,
                filename=filename,
            )

        # With diarization the API returns a running aggregate per result;
        # the LAST result's word list is the complete diarized output.
        last_result = response.results[-1]
        words = last_result.alternatives[0].words if last_result.alternatives else []

        detected_languages = list(dict.fromkeys(
            r.language_code for r in response.results if r.language_code
        ))

        utterances = SpeechTranscriber._group_into_utterances(words)
        unique_speakers = sorted({u.speaker for u in utterances})
        full_transcript = " ".join(u.text for u in utterances)

        return TranscriptionResult(
            transcript=full_transcript,
            utterances=utterances,
            detected_languages=detected_languages,
            speakers=unique_speakers,
            speaker_count=len(unique_speakers),
            filename=filename,
        )

    @staticmethod
    def _group_into_utterances(words) -> list[Utterance]:
        """Group consecutive words with the same speaker_label into Utterance objects."""
        if not words:
            return []

        utterances: list[Utterance] = []
        current_speaker = words[0].speaker_label
        current_words   = [words[0].word]

        for w in words[1:]:
            if w.speaker_label == current_speaker:
                current_words.append(w.word)
            else:
                utterances.append(Utterance(speaker=current_speaker, text=" ".join(current_words)))
                current_speaker = w.speaker_label
                current_words   = [w.word]

        utterances.append(Utterance(speaker=current_speaker, text=" ".join(current_words)))
        return utterances