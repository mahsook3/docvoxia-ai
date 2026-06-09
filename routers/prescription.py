"""
routers/prescription.py
------------------------
Prescription and care-plan endpoints (backed by PrescriptionAgent).

POST /prescription/{user_id}/generate  — generate Rx + follow-up + FHIR resources
POST /prescription/{user_id}/approve   — finalise a pending prescription
GET  /prescription/{user_id}/status    — check prescription status for a session
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

_prescription_agent = None
# In-memory store for pending approvals: { user_id: prescription_dict }
_pending: dict = {}


def _get_prescription_agent():
    global _prescription_agent
    if _prescription_agent is None:
        from agents.prescription_agent import build_prescription_agent
        _prescription_agent = build_prescription_agent()
    return _prescription_agent


# ── Request models ────────────────────────────────────────────────────────────

class GeneratePrescriptionRequest(BaseModel):
    target_language: str = "en"
    require_approval: bool = True


class ApproveRequest(BaseModel):
    """
    Optionally override fields before finalising.
    Pass patient_id if not already stored on the session.
    """
    patient_id: Optional[str] = None
    override_prescription: Optional[str] = None
    override_follow_up: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/prescription/{user_id}/generate", tags=["Prescription"])
async def generate_prescription(user_id: str, body: GeneratePrescriptionRequest):
    """
    Generate a full prescription, follow-up instructions, patient summary,
    and FHIR MedicationRequest list for a completed clinical session.

    If `require_approval=True` (default), the prescription is held in
    `pending_approval` state and must be confirmed via POST /approve before
    FHIR resources are written.
    """
    from utils.session_store import get_session as _get
    session = _get(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    if not session.get("complete"):
        raise HTTPException(
            status_code=409,
            detail="Session is not yet complete. Finish the clinical intake first.",
        )

    from agents.prescription_agent import generate_session_prescription
    result = await generate_session_prescription(
        agent=_get_prescription_agent(),
        user_id=user_id,
        target_language=body.target_language,
        require_approval=body.require_approval,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    # Cache pending prescription for the approval step
    if result.get("status") == "pending_approval":
        _pending[user_id] = result

    return result


@router.post("/prescription/{user_id}/approve", tags=["Prescription"])
async def approve_prescription(user_id: str, body: ApproveRequest):
    """
    Human-in-the-loop approval step.
    Writes FHIR MedicationRequest resources and marks the prescription as finalised.
    """
    from utils.session_store import get_session as _get
    session = _get(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    draft = _pending.get(user_id)
    if not draft:
        raise HTTPException(
            status_code=404,
            detail="No pending prescription found for this session. "
                   "Call POST /generate first.",
        )

    pid = body.patient_id or session.get("patient_id")
    if not pid:
        raise HTTPException(
            status_code=422,
            detail="patient_id is required to finalise. "
                   "Supply it in the request body or link it to the session.",
        )

    # Apply optional overrides
    if body.override_prescription:
        draft["prescription"] = body.override_prescription
    if body.override_follow_up:
        draft["follow_up"] = body.override_follow_up

    fhir_results = []
    fhir_section = draft.get("fhir_resources", "")

    # Best-effort: write MedicationRequests extracted by the agent
    # The agent outputs FHIR resources as text; we attempt structured extraction.
    import re, json as _json
    med_blocks = re.findall(r"\{[^{}]*MedicationRequest[^{}]*\}", fhir_section, re.DOTALL)
    for block in med_blocks:
        try:
            from tools.fhir_tools import fhir_create_medication_request
            med = _json.loads(block)
            name      = med.get("medicationCodeableConcept", {}).get("text", "Unknown")
            dosage    = med.get("dosageInstruction", [{}])[0].get("text", "")
            dose_text, _, frequency = dosage.partition(" — ")
            res = fhir_create_medication_request(
                patient_id=pid,
                medication_name=name,
                dose_text=dose_text.strip(),
                frequency=frequency.strip() or "as directed",
            )
            fhir_results.append(res)
        except Exception as exc:
            logger.warning("Could not write MedicationRequest block: %s", exc)

    # Remove from pending
    _pending.pop(user_id, None)

    return {
        "status":           "finalized",
        "patient_id":       pid,
        "prescription":     draft.get("prescription"),
        "follow_up":        draft.get("follow_up"),
        "patient_summary":  draft.get("patient_summary"),
        "fhir_resources_written": len(fhir_results),
        "fhir_results":     fhir_results,
    }


@router.get("/prescription/{user_id}/status", tags=["Prescription"])
async def prescription_status(user_id: str):
    """
    Check whether a prescription has been generated and/or approved for a session.
    """
    from utils.session_store import get_session as _get
    if not _get(user_id):
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    pending = _pending.get(user_id)
    return {
        "user_id":             user_id,
        "prescription_status": "pending_approval" if pending else "none",
        "draft_available":     pending is not None,
    }
