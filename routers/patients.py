"""
routers/patients.py
--------------------
Patient / FHIR endpoints.

GET    /patients              — list patients (optional ?limit=N)
GET    /patients/{patient_id} — fetch a single patient
POST   /patients              — register a new patient
GET    /patients/{patient_id}/context — full structured medical context
POST   /patients/{patient_id}/visit-note — write a visit note to FHIR
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class RegisterPatientRequest(BaseModel):
    given_name: str
    family_name: str
    birth_date: str          # ISO date e.g. "1990-05-14"
    gender: str              # "male" | "female" | "other" | "unknown"
    phone: Optional[str] = None


class VisitNoteRequest(BaseModel):
    note_text: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/patients", tags=["Patients / FHIR"])
async def list_patients(limit: Optional[int] = Query(None, ge=1, le=500)):
    """Return a list of Patient resources from the FHIR store."""
    try:
        from get_patient import list_patients as _list
        return {"patients": _list(limit=limit)}
    except Exception as exc:
        logger.exception("list_patients failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/patients/{patient_id}", tags=["Patients / FHIR"])
async def get_patient(patient_id: str):
    """Fetch a single Patient resource by FHIR ID."""
    try:
        from get_patient import get_patient_by_id
        patient = get_patient_by_id(patient_id)
        if patient is None:
            raise HTTPException(status_code=404, detail=f"Patient '{patient_id}' not found.")
        return patient
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_patient failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/patients", status_code=201, tags=["Patients / FHIR"])
async def register_patient(body: RegisterPatientRequest):
    """Register a new patient in the FHIR store."""
    try:
        from tools.fhir_tools import register_patient as _register
        return _register(
            given_name=body.given_name,
            family_name=body.family_name,
            birth_date=body.birth_date,
            gender=body.gender,
            phone=body.phone,
        )
    except Exception as exc:
        logger.exception("register_patient failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/patients/{patient_id}/context", tags=["Patients / FHIR"])
async def get_patient_context(
    patient_id: str,
    force_refresh: bool = Query(False),
):
    """
    Return a structured text summary of the patient's full medical history:
    demographics, conditions, medications, observations, allergies, appointments.
    """
    try:
        from fhir_client import build_patient_context
        context = build_patient_context(patient_id=patient_id, force_refresh=force_refresh)
        return {"patient_id": patient_id, "context": context}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("get_patient_context failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/patients/{patient_id}/visit-note", status_code=201, tags=["Patients / FHIR"])
async def write_visit_note(patient_id: str, body: VisitNoteRequest):
    """
    Persist a visit note to FHIR as a DocumentReference resource.
    The note is base64-encoded and stored against the given patient.
    """
    if not body.note_text.strip():
        raise HTTPException(status_code=422, detail="note_text must not be empty.")
    try:
        from fhir_client import write_visit_note as _write
        result = _write(note_text=body.note_text, patient_id=patient_id)
        return {"status": "created", "resource": result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("write_visit_note failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
