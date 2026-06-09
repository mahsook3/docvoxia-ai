"""
utils/session_store.py
-----------------------
In-memory session store (swap for Redis in production).

Holds per-user conversation state shared across all ADK agents so that
PatientCareAgent, ClinicalAssistantAgent, and PrescriptionAgent can all
read/write the same context without coupling directly to each other.
"""

import time
import threading
import uuid
from typing import Any, Dict, List, Optional

_SESSIONS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
SESSION_TTL = 3600  # 1 hour


def _now() -> float:
    return time.monotonic()


def create_session(session_type_id: str, session_type_meta: Dict[str, Any]) -> str:
    """Create a new session and return the user_id (session key)."""
    user_id = str(uuid.uuid4())
    with _LOCK:
        _SESSIONS[user_id] = {
            "user_id":          user_id,
            "session_type_id":  session_type_id,
            "session_type":     session_type_meta,
            "history":          [],         # list of {role, content} turns
            "medical_terms":    {           # accumulated structured terms
                "conditions":   [],
                "medications":  [],
                "observations": [],
                "symptoms":     [],
                "diagnoses":    [],
            },
            "patient_id":       None,       # linked FHIR patient
            "complete":         False,
            "created_at":       _now(),
            "updated_at":       _now(),
        }
    return user_id


def get_session(user_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        s = _SESSIONS.get(user_id)
        if s and (_now() - s["updated_at"]) < SESSION_TTL:
            return s
        if s:
            del _SESSIONS[user_id]
        return None


def update_session(user_id: str, patch: Dict[str, Any]) -> bool:
    with _LOCK:
        s = _SESSIONS.get(user_id)
        if not s:
            return False
        s.update(patch)
        s["updated_at"] = _now()
        return True


def append_history(user_id: str, role: str, content: str) -> bool:
    with _LOCK:
        s = _SESSIONS.get(user_id)
        if not s:
            return False
        s["history"].append({"role": role, "content": content})
        s["updated_at"] = _now()
        return True


def delete_session(user_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(user_id, None)


def purge_expired() -> int:
    """Remove stale sessions; returns number of sessions removed."""
    now = _now()
    with _LOCK:
        stale = [uid for uid, s in _SESSIONS.items() if (now - s["updated_at"]) >= SESSION_TTL]
        for uid in stale:
            del _SESSIONS[uid]
    return len(stale)