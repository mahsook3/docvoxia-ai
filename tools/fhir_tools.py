"""
tools/fhir_tools.py
--------------------
ADK-compatible tool functions wrapping the Google Cloud Healthcare FHIR API.

All functions have typed signatures and docstrings so Google ADK can
auto-generate tool schemas from them.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── NOTE ──────────────────────────────────────────────────────────────────────
# The actual FHIR client (fhir_client.py) is imported lazily so the module
# can be loaded even without GCP credentials (useful for testing).
# ─────────────────────────────────────────────────────────────────────────────

def _client():
    from fhir_client import (
        build_patient_context,
        write_visit_note,
        fetch_patient,
        fetch_conditions,
        fetch_medications,
        fetch_observations,
        fetch_allergies,
        fetch_appointments,
        FHIR_BASE,
        _get_client,
        _fhir,
    )
    return {
        "build_patient_context": build_patient_context,
        "write_visit_note":      write_visit_note,
        "fetch_patient":         fetch_patient,
        "FHIR_BASE":             FHIR_BASE,
        "_get_client":           _get_client,
        "_fhir":                 _fhir,
    }


def fhir_get_patient_context(patient_id: str, force_refresh: bool = False) -> str:
    """
    Fetch and format a complete patient medical context from FHIR.

    Args:
        patient_id:     The FHIR Patient resource ID.
        force_refresh:  Bypass the 5-minute cache if True.

    Returns:
        A structured text summary of demographics, conditions,
        medications, observations, allergies, and appointments.
    """
    c = _client()
    return c["build_patient_context"](patient_id=patient_id, force_refresh=force_refresh)


def lookup_patient(patient_id: str) -> Dict[str, Any]:
    """
    Look up a FHIR Patient resource by ID.

    Args:
        patient_id: FHIR Patient resource ID.

    Returns:
        The Patient resource dict, or {"error": "..."} if not found.
    """
    from get_patient import get_patient_by_id
    patient = get_patient_by_id(patient_id)
    if patient is None:
        return {"error": f"Patient {patient_id} not found"}
    return patient


def register_patient(
    given_name: str,
    family_name: str,
    birth_date: str,
    gender: str,
    phone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register a new patient in the FHIR store.

    Args:
        given_name:  Patient's given (first) name.
        family_name: Patient's family (last) name.
        birth_date:  ISO date string e.g. "1990-05-14".
        gender:      "male" | "female" | "other" | "unknown"
        phone:       Optional phone number string.

    Returns:
        The created FHIR Patient resource with an assigned id.
    """
    from get_patient import create_patient

    resource: Dict[str, Any] = {
        "resourceType": "Patient",
        "name": [{"use": "official", "given": [given_name], "family": family_name}],
        "birthDate": birth_date,
        "gender": gender,
    }
    if phone:
        resource["telecom"] = [{"system": "phone", "value": phone, "use": "mobile"}]

    return create_patient(resource)


def book_appointment(
    patient_id: str,
    description: str,
    start: str,
    end: str,
    practitioner_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create an Appointment resource for a patient.

    Args:
        patient_id:       FHIR Patient ID.
        description:      Human-readable appointment description.
        start:            ISO datetime string for appointment start.
        end:              ISO datetime string for appointment end.
        practitioner_id:  Optional FHIR Practitioner ID.

    Returns:
        Created FHIR Appointment resource.
    """
    c = _client()
    FHIR_BASE = c["FHIR_BASE"]
    client    = c["_get_client"]()
    fhir      = c["_fhir"](client)

    participants = [
        {"actor": {"reference": f"Patient/{patient_id}"}, "status": "accepted"}
    ]
    if practitioner_id:
        participants.append({
            "actor": {"reference": f"Practitioner/{practitioner_id}"},
            "status": "accepted",
        })

    appt = {
        "resourceType": "Appointment",
        "status": "booked",
        "description": description,
        "start": start,
        "end": end,
        "participant": participants,
    }

    return fhir.create(parent=FHIR_BASE, type="Appointment", body=appt).execute()


def fhir_write_visit_note(
    note_text: str,
    patient_id: str,
) -> Dict[str, Any]:
    """
    Persist a clinical visit note to FHIR as a DocumentReference.

    Args:
        note_text:  Full text of the visit note.
        patient_id: FHIR Patient resource ID.

    Returns:
        The created FHIR DocumentReference resource.
    """
    c = _client()
    return c["write_visit_note"](note_text=note_text, patient_id=patient_id)


def fhir_create_condition(
    patient_id: str,
    condition_name: str,
    status: str = "active",
    onset_date: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a FHIR Condition resource for a patient.

    Args:
        patient_id:      FHIR Patient ID.
        condition_name:  Human-readable condition name.
        status:          "active" | "resolved" | "inactive"
        onset_date:      ISO date string for onset.
        note:            Optional clinical note text.

    Returns:
        Created FHIR Condition resource.
    """
    c = _client()
    FHIR_BASE = c["FHIR_BASE"]
    client    = c["_get_client"]()
    fhir      = c["_fhir"](client)

    resource: Dict[str, Any] = {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": status}]
        },
        "code": {"text": condition_name},
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    if onset_date:
        resource["onsetDateTime"] = onset_date
    if note:
        resource["note"] = [{"text": note}]

    return fhir.create(parent=FHIR_BASE, type="Condition", body=resource).execute()


def fhir_create_medication_request(
    patient_id: str,
    medication_name: str,
    dose_text: str,
    frequency: str,
    duration_days: Optional[int] = None,
    prescriber_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a FHIR MedicationRequest resource.

    Args:
        patient_id:       FHIR Patient ID.
        medication_name:  Name of the medication.
        dose_text:        Dosage instructions e.g. "500mg oral".
        frequency:        Frequency e.g. "twice daily".
        duration_days:    Optional treatment duration in days.
        prescriber_id:    Optional FHIR Practitioner ID.

    Returns:
        Created FHIR MedicationRequest resource.
    """
    c = _client()
    FHIR_BASE = c["FHIR_BASE"]
    client    = c["_get_client"]()
    fhir      = c["_fhir"](client)

    dosage: Dict[str, Any] = {
        "text": f"{dose_text} — {frequency}",
    }
    if duration_days:
        dosage["timing"] = {
            "repeat": {"boundsDuration": {"value": duration_days, "unit": "d",
                                          "system": "http://unitsofmeasure.org", "code": "d"}}
        }

    resource: Dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"text": medication_name},
        "subject": {"reference": f"Patient/{patient_id}"},
        "dosageInstruction": [dosage],
    }
    if prescriber_id:
        resource["requester"] = {"reference": f"Practitioner/{prescriber_id}"}

    return fhir.create(parent=FHIR_BASE, type="MedicationRequest", body=resource).execute()


def fhir_create_observation(
    patient_id: str,
    observation_name: str,
    value: float,
    unit: str,
    loinc_code: Optional[str] = None,
    effective_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a FHIR Observation resource (e.g. lab result, vital sign).

    Args:
        patient_id:        FHIR Patient ID.
        observation_name:  Human-readable name.
        value:             Numeric result value.
        unit:              Unit string e.g. "mg/dL", "mmHg".
        loinc_code:        Optional LOINC code string.
        effective_date:    ISO datetime for when the observation was recorded.

    Returns:
        Created FHIR Observation resource.
    """
    c = _client()
    FHIR_BASE = c["FHIR_BASE"]
    client    = c["_get_client"]()
    fhir      = c["_fhir"](client)

    coding: Dict[str, Any] = {"display": observation_name}
    if loinc_code:
        coding["system"] = "http://loinc.org"
        coding["code"]   = loinc_code

    resource: Dict[str, Any] = {
        "resourceType": "Observation",
        "status": "final",
        "code": {"coding": [coding], "text": observation_name},
        "subject": {"reference": f"Patient/{patient_id}"},
        "valueQuantity": {
            "value": value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
        },
    }
    if effective_date:
        resource["effectiveDateTime"] = effective_date

    return fhir.create(parent=FHIR_BASE, type="Observation", body=resource).execute()