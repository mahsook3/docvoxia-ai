"""
routers/clinical.py
--------------------
Clinical Assistant endpoints (backed by ClinicalAssistantAgent).

POST /clinical/{user_id}/check-completeness  — analyse query, extract terms
POST /clinical/{user_id}/clarify             — submit a clarification answer
GET  /clinical/{user_id}/clarifying-question — get the next question to ask
GET  /clinical/{user_id}/summary             — get final formatted clinical summary
POST /clinical/{user_id}/soap-note           — generate + optionally persist SOAP note
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

_clinical_agent = None


def _get_clinical_agent():
    global _clinical_agent
    if _clinical_agent is None:
        from agents.clinical_assistant_agent import build_clinical_assistant_agent
        _clinical_agent = build_clinical_assistant_agent()
    return _clinical_agent


# ── Request models ────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str


class ClarificationRequest(BaseModel):
    clarification: str


class SoapNoteRequest(BaseModel):
    persist: bool = False          # if True, write to FHIR via fhir_write_visit_note
    patient_id: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/clinical/{user_id}/check-completeness", tags=["Clinical Assistant"])
async def check_completeness(user_id: str, body: QueryRequest):
    """
    Analyse a clinical query for completeness.
    Returns extracted medical terms and a `complete` boolean.
    """
    from utils.session_store import get_session as _get
    if not _get(user_id):
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    if not body.query.strip():
        raise HTTPException(status_code=422, detail="query must not be empty.")

    from agents.clinical_assistant_agent import check_completeness as _check
    result = await _check(
        agent=_get_clinical_agent(),
        user_id=user_id,
        query=body.query,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/clinical/{user_id}/clarify", tags=["Clinical Assistant"])
async def clarify(user_id: str, body: ClarificationRequest):
    """
    Submit a clarification answer and re-evaluate completeness.
    """
    from utils.session_store import get_session as _get
    if not _get(user_id):
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    if not body.clarification.strip():
        raise HTTPException(status_code=422, detail="clarification must not be empty.")

    from agents.clinical_assistant_agent import answer_clarification
    result = await answer_clarification(
        agent=_get_clinical_agent(),
        user_id=user_id,
        clarification=body.clarification,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/clinical/{user_id}/clarifying-question", tags=["Clinical Assistant"])
async def get_clarifying_question(user_id: str):
    """
    Ask the ClinicalAssistantAgent what the most important next question is.
    """
    from utils.session_store import get_session as _get
    if not _get(user_id):
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    from agents.clinical_assistant_agent import generate_clarifying_question
    result = await generate_clarifying_question(
        agent=_get_clinical_agent(),
        user_id=user_id,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/clinical/{user_id}/summary", tags=["Clinical Assistant"])
async def get_clinical_summary(user_id: str):
    """
    Generate a formatted clinical summary for the session (for the medical record).
    """
    from utils.session_store import get_session as _get
    if not _get(user_id):
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    from agents.clinical_assistant_agent import get_final_info
    result = await get_final_info(
        agent=_get_clinical_agent(),
        user_id=user_id,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/clinical/{user_id}/soap-note", status_code=201, tags=["Clinical Assistant"])
async def generate_soap_note(user_id: str, body: SoapNoteRequest):
    """
    Generate a SOAP note for the session.
    If `persist=True` and `patient_id` is provided, write to FHIR as a DocumentReference.
    """
    from utils.session_store import get_session as _get
    session = _get(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    # Get summary text from the agent
    from agents.clinical_assistant_agent import get_final_info
    summary = await get_final_info(agent=_get_clinical_agent(), user_id=user_id)

    if "error" in summary:
        raise HTTPException(status_code=500, detail=summary["error"])

    note_text = summary.get("formatted_info", "")
    fhir_result = None

    if body.persist:
        pid = body.patient_id or session.get("patient_id")
        if not pid:
            raise HTTPException(
                status_code=422,
                detail="patient_id is required to persist the note. "
                       "Supply it in the request body or link it to the session.",
            )
        try:
            from tools.fhir_tools import fhir_write_visit_note
            fhir_result = fhir_write_visit_note(note_text=note_text, patient_id=pid)
        except Exception as exc:
            logger.exception("FHIR write failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"FHIR write error: {exc}")

    return {
        "soap_note":    note_text,
        "persisted":    body.persist,
        "fhir_resource": fhir_result,
    }
