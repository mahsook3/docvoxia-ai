"""
tools/prescription_tools.py
-----------------------------
ADK-compatible tools for prescription generation and FHIR care planning.

Exposed tools:
  - generate_prescription       : build a structured Rx document from clinical data
  - create_medication_request   : write a FHIR MedicationRequest resource
  - create_care_plan            : write a FHIR CarePlan resource
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# generate_prescription
# ---------------------------------------------------------------------------

def generate_prescription(
    patient_name: str,
    patient_id: str,
    medications: List[Dict[str, Any]],
    diagnosis: str,
    prescriber_name: Optional[str] = None,
    prescriber_id: Optional[str] = None,
    follow_up_days: Optional[int] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a structured prescription document from clinical data.

    Args:
        patient_name:    Full name of the patient.
        patient_id:      FHIR Patient resource ID.
        medications:     List of medication dicts, each with keys:
                           name, dose, route, frequency, duration_days (optional),
                           special_instructions (optional).
        diagnosis:       Primary diagnosis / indication for the prescription.
        prescriber_name: Optional name of the prescribing physician.
        prescriber_id:   Optional FHIR Practitioner ID.
        follow_up_days:  Number of days until follow-up (e.g. 7 for one week).
        notes:           Additional clinical notes.

    Returns:
        Dict with keys:
          - "prescription_text" : str  — human-readable prescription
          - "medications"       : list — validated medication list
          - "prescriber"        : str
          - "date"              : str
          - "follow_up_date"    : str or None
    """
    today = datetime.date.today()

    follow_up_date = None
    if follow_up_days and follow_up_days > 0:
        follow_up_date = (today + datetime.timedelta(days=follow_up_days)).isoformat()

    # Build human-readable Rx
    lines = [
        "PRESCRIPTION",
        "=" * 60,
        f"Patient   : {patient_name}  (ID: {patient_id})",
        f"Diagnosis : {diagnosis}",
        f"Date      : {today.isoformat()}",
    ]
    if prescriber_name:
        lines.append(f"Prescriber: {prescriber_name}" + (f"  (ID: {prescriber_id})" if prescriber_id else ""))
    lines.append("")
    lines.append("Medications:")
    lines.append("-" * 40)

    validated_meds = []
    for idx, med in enumerate(medications, start=1):
        name     = med.get("name", "Unknown")
        dose     = med.get("dose", "as prescribed")
        route    = med.get("route", "oral")
        freq     = med.get("frequency", "as directed")
        duration = med.get("duration_days")
        special  = med.get("special_instructions", "")

        duration_str = f"for {duration} days" if duration else ""
        line = f"{idx}. {name}  —  {dose} {route}  {freq}  {duration_str}".strip()
        if special:
            line += f"\n   ⚠ {special}"
        lines.append(line)

        validated_meds.append({
            "name":                 name,
            "dose":                 dose,
            "route":                route,
            "frequency":            freq,
            "duration_days":        duration,
            "special_instructions": special,
        })

    lines.append("")
    if follow_up_date:
        lines.append(f"Follow-up : {follow_up_date}")
    if notes:
        lines.append(f"Notes     : {notes}")
    lines.append("=" * 60)

    return {
        "prescription_text": "\n".join(lines),
        "medications":       validated_meds,
        "prescriber":        prescriber_name or "Attending Physician",
        "date":              today.isoformat(),
        "follow_up_date":    follow_up_date,
    }


# ---------------------------------------------------------------------------
# create_medication_request
# ---------------------------------------------------------------------------

def create_medication_request(
    patient_id: str,
    medication_name: str,
    dose_text: str,
    frequency: str,
    duration_days: Optional[int] = None,
    prescriber_id: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a FHIR MedicationRequest resource and persist it to the FHIR store.

    Args:
        patient_id:       FHIR Patient resource ID.
        medication_name:  Name of the medication (generic or brand).
        dose_text:        Dosage instructions (e.g. "500mg oral").
        frequency:        Frequency string (e.g. "twice daily", "every 8 hours").
        duration_days:    Optional treatment duration in days.
        prescriber_id:    Optional FHIR Practitioner ID of the prescriber.
        note:             Optional additional instruction text.

    Returns:
        The created FHIR MedicationRequest resource dict, or an error dict.
    """
    try:
        from tools.fhir_tools import fhir_create_medication_request
        return fhir_create_medication_request(
            patient_id=patient_id,
            medication_name=medication_name,
            dose_text=dose_text,
            frequency=frequency,
            duration_days=duration_days,
            prescriber_id=prescriber_id,
        )
    except Exception as exc:
        logger.exception("create_medication_request failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# create_care_plan
# ---------------------------------------------------------------------------

def create_care_plan(
    patient_id: str,
    title: str,
    description: str,
    activities: List[Dict[str, Any]],
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    author_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a FHIR CarePlan resource and persist it to the FHIR store.

    Args:
        patient_id:   FHIR Patient resource ID.
        title:        Short title for the care plan (e.g. "Post-Discharge Plan").
        description:  Human-readable description of the overall plan.
        activities:   List of activity dicts, each with:
                        - "description" (str, required)
                        - "kind"        (str, optional — e.g. "MedicationRequest")
                        - "status"      (str, optional — default "not-started")
        period_start: ISO date string for plan start (defaults to today).
        period_end:   ISO date string for plan end (e.g. follow-up date).
        author_id:    Optional FHIR Practitioner ID of the care plan author.

    Returns:
        The created FHIR CarePlan resource dict, or an error dict.
    """
    today = datetime.date.today().isoformat()

    fhir_activities = []
    for act in activities:
        detail: Dict[str, Any] = {
            "status":      act.get("status", "not-started"),
            "description": act.get("description", ""),
        }
        if act.get("kind"):
            detail["kind"] = act["kind"]
        fhir_activities.append({"detail": detail})

    resource: Dict[str, Any] = {
        "resourceType": "CarePlan",
        "status":       "active",
        "intent":       "plan",
        "title":        title,
        "description":  description,
        "subject":      {"reference": f"Patient/{patient_id}"},
        "period": {
            "start": period_start or today,
        },
        "activity": fhir_activities,
    }

    if period_end:
        resource["period"]["end"] = period_end

    if author_id:
        resource["author"] = {"reference": f"Practitioner/{author_id}"}

    try:
        from fhir_client import FHIR_BASE, _get_client, _fhir
        client = _get_client()
        fhir   = _fhir(client)
        return fhir.create(parent=FHIR_BASE, type="CarePlan", body=resource).execute()
    except Exception as exc:
        logger.exception("create_care_plan FHIR write failed: %s", exc)
        # Return the resource dict without an ID so callers can still use it
        resource["_write_error"] = str(exc)
        return resource