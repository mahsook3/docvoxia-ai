"""
routers/sessions.py
--------------------
Session management endpoints (backed by session_store + session_type_registry).

POST   /sessions                    — create a new session
GET    /sessions/{user_id}          — get session state
DELETE /sessions/{user_id}          — delete (end) a session
POST   /sessions/{user_id}/message  — send a patient message (runs PatientCareAgent)
GET    /session-types               — list available session types
POST   /session-types               — create a custom session type
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# Agent singleton (built once, shared across requests)
_patient_care_agent = None


def _get_patient_care_agent():
    global _patient_care_agent
    if _patient_care_agent is None:
        from agents.patient_care_agent import build_patient_care_agent
        _patient_care_agent = build_patient_care_agent()
    return _patient_care_agent


# ── Request / Response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    session_type_id: str
    patient_id: Optional[str] = None    # pre-link to a FHIR patient if known


class SessionMessageRequest(BaseModel):
    message: str


class CreateSessionTypeRequest(BaseModel):
    name: str
    description: str
    required_fields: List[str]


# ── Session-type endpoints ────────────────────────────────────────────────────

@router.get("/session-types", tags=["Sessions"])
async def list_session_types():
    """Return all registered session types."""
    from utils.session_type_registry import list_session_types as _list
    return {"session_types": _list()}


@router.post("/session-types", status_code=201, tags=["Sessions"])
async def create_session_type(body: CreateSessionTypeRequest):
    """Register a custom session type."""
    from utils.session_type_registry import create_session_type as _create
    type_id = _create(
        name=body.name,
        description=body.description,
        required_fields=body.required_fields,
    )
    return {"type_id": type_id, "name": body.name}


# ── Session lifecycle ─────────────────────────────────────────────────────────

@router.post("/sessions", status_code=201, tags=["Sessions"])
async def create_session(body: CreateSessionRequest):
    """
    Create a new conversation session.
    session_type_id must match one of the registered session types.
    """
    from utils.session_type_registry import get_session_type
    from utils.session_store import create_session as _create, update_session

    session_type = get_session_type(body.session_type_id)
    if not session_type:
        raise HTTPException(
            status_code=404,
            detail=f"Session type '{body.session_type_id}' not found. "
                   f"Call GET /session-types for valid IDs.",
        )

    user_id = _create(
        session_type_id=body.session_type_id,
        session_type_meta=session_type,
    )

    if body.patient_id:
        update_session(user_id, {"patient_id": body.patient_id})

    return {
        "user_id":      user_id,
        "session_type": session_type,
        "patient_id":   body.patient_id,
        "status":       "created",
    }


@router.get("/sessions/{user_id}", tags=["Sessions"])
async def get_session(user_id: str):
    """Return current session state."""
    from utils.session_store import get_session as _get
    session = _get(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    return session


@router.delete("/sessions/{user_id}", tags=["Sessions"])
async def delete_session(user_id: str):
    """End and delete a session."""
    from utils.session_store import delete_session as _delete, get_session as _get
    if not _get(user_id):
        raise HTTPException(status_code=404, detail="Session not found or already expired.")
    _delete(user_id)
    return {"status": "deleted", "user_id": user_id}


# ── Conversation turn ─────────────────────────────────────────────────────────

@router.post("/sessions/{user_id}/message", tags=["Sessions"])
async def send_message(user_id: str, body: SessionMessageRequest):
    """
    Send a patient message to the PatientCareAgent.
    Returns the agent reply and whether intake is complete.
    """
    from utils.session_store import get_session as _get
    if not _get(user_id):
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    if not body.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty.")

    from agents.patient_care_agent import run_intake_turn
    result = await run_intake_turn(
        agent=_get_patient_care_agent(),
        user_id=user_id,
        user_message=body.message,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result
