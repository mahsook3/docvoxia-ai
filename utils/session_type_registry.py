"""
utils/session_type_registry.py
-------------------------------
In-memory registry for session types (e.g. OPD Prescription, Triage, Follow-up).
In production, back this with Firestore or Cloud SQL.
"""

import uuid
import threading
from typing import Any, Dict, List, Optional

_REGISTRY: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()

# Seed defaults on import
_DEFAULTS = [
    {
        "name": "OPD Prescription",
        "description": "Outpatient consultation leading to a prescription.",
        "required_fields": ["chief_complaint", "symptoms", "duration", "allergies"],
    },
    {
        "name": "Triage Assessment",
        "description": "Emergency triage to determine acuity level.",
        "required_fields": ["chief_complaint", "vitals", "pain_scale"],
    },
    {
        "name": "Follow-up Visit",
        "description": "Post-treatment follow-up for chronic condition management.",
        "required_fields": ["previous_diagnosis", "current_symptoms", "medications"],
    },
    {
        "name": "Lab Result Review",
        "description": "Doctor reviews lab results with patient.",
        "required_fields": ["lab_type", "results", "interpretation"],
    },
]


def _seed():
    for d in _DEFAULTS:
        type_id = str(uuid.uuid4())
        _REGISTRY[type_id] = {"type_id": type_id, **d}


_seed()


def create_session_type(
    name: str,
    description: str,
    required_fields: List[str],
) -> str:
    """Register a new session type; returns its type_id."""
    type_id = str(uuid.uuid4())
    with _LOCK:
        _REGISTRY[type_id] = {
            "type_id":        type_id,
            "name":           name,
            "description":    description,
            "required_fields": required_fields,
        }
    return type_id


def get_session_type(type_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        return _REGISTRY.get(type_id)


def list_session_types() -> List[Dict[str, Any]]:
    with _LOCK:
        return list(_REGISTRY.values())