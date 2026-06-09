"""
fhir_client.py
--------------
Fetches a patient's complete medical context from GCP Cloud Healthcare FHIR.
Also provides write_visit_note() used by the Doctor Summary Tool to persist
the post-call visit note back to FHIR as a DocumentReference resource.

Optimised: single shared API client + all resources fetched in parallel
via a ThreadPoolExecutor, cutting 5-6 sequential round-trips down to 1.

Patient ID is passed explicitly at call time rather than read from env, so
a single server process can serve multiple patients concurrently.
The env-var PATIENT_ID is kept as a convenience default for local testing.
"""

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import base64

from dotenv import load_dotenv
from googleapiclient import discovery

_env_path = Path(__file__).with_name(".env")
load_dotenv(dotenv_path=_env_path if _env_path.exists() else None)

PROJECT_ID    = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION      = os.environ["GOOGLE_CLOUD_LOCATION"]
DATASET_ID    = os.environ["HEALTHCARE_DATASET_ID"]
FHIR_STORE_ID = os.environ["HEALTHCARE_FHIR_STORE_ID"]
# Fallback only — callers should supply patient_id explicitly.
_DEFAULT_PATIENT_ID = os.environ.get("PATIENT_ID", "")

FHIR_BASE = (
    f"projects/{PROJECT_ID}/locations/{LOCATION}"
    f"/datasets/{DATASET_ID}/fhirStores/{FHIR_STORE_ID}"
)

# ── Shared client (built once, reused for all calls) ─────────────────────────
_CLIENT_LOCK = threading.Lock()
_shared_client = None

def _get_client():
    """Return a module-level shared Healthcare API client (lazy-init, thread-safe)."""
    global _shared_client
    if _shared_client is None:
        with _CLIENT_LOCK:
            if _shared_client is None:          # double-checked locking
                _shared_client = discovery.build("healthcare", "v1")
    return _shared_client


def _fhir(client):
    return client.projects().locations().datasets().fhirStores().fhir()


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def _search(resource_type: str, params: Dict) -> List[Dict]:
    """Search for FHIR resources and return the entry list."""
    client = _get_client()
    result = (
        _fhir(client)
        .search(parent=FHIR_BASE, resourceType=resource_type, body=params)
        .execute()
    )
    return [e["resource"] for e in result.get("entry", [])]


def fetch_patient(patient_id: str) -> Dict[str, Any]:
    client = _get_client()
    return (
        _fhir(client)
        .read(name=f"{FHIR_BASE}/fhir/Patient/{patient_id}")
        .execute()
    )


def fetch_conditions(patient_id: str) -> List[Dict]:
    return _search("Condition", {"resourceType": "Condition", "subject": f"Patient/{patient_id}"})


def fetch_medications(patient_id: str) -> List[Dict]:
    return _search("MedicationStatement", {"resourceType": "MedicationStatement", "subject": f"Patient/{patient_id}"})


def fetch_observations(patient_id: str) -> List[Dict]:
    return _search("Observation", {"resourceType": "Observation", "subject": f"Patient/{patient_id}"})


def fetch_allergies(patient_id: str) -> List[Dict]:
    return _search("AllergyIntolerance", {"resourceType": "AllergyIntolerance", "patient": f"Patient/{patient_id}"})


def fetch_appointments(patient_id: str) -> List[Dict]:
    return _search("Appointment", {"resourceType": "Appointment", "actor": f"Patient/{patient_id}"})


# ── Parallel fetch all resources ──────────────────────────────────────────────

def fetch_all_parallel(patient_id: str) -> Tuple[Dict, List, List, List, List, List]:
    """
    Fire all 6 FHIR requests concurrently in a thread pool.
    Returns (patient, conditions, medications, observations, allergies, appointments).
    """
    tasks = {
        "patient":      lambda: fetch_patient(patient_id),
        "conditions":   lambda: fetch_conditions(patient_id),
        "medications":  lambda: fetch_medications(patient_id),
        "observations": lambda: fetch_observations(patient_id),
        "allergies":    lambda: fetch_allergies(patient_id),
        "appointments": lambda: fetch_appointments(patient_id),
    }

    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_to_key = {pool.submit(fn): key for key, fn in tasks.items()}
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            results[key] = future.result()

    return (
        results["patient"],
        results["conditions"],
        results["medications"],
        results["observations"],
        results["allergies"],
        results["appointments"],
    )


# ── Doctor summary tool: write visit note back to FHIR ───────────────────────

def write_visit_note(note_text: str, patient_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Persist a post-call visit note to FHIR as a DocumentReference resource.
    Called by the Doctor Summary Tool at the end of each voice session.

    patient_id: the patient this note belongs to.  Falls back to the
                PATIENT_ID env var if not supplied (local testing only).

    Returns the created FHIR resource dict.
    """
    pid = (patient_id or _DEFAULT_PATIENT_ID).strip()
    if not pid:
        raise ValueError("patient_id is required to write a visit note")

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    encoded = base64.b64encode(note_text.encode("utf-8")).decode("ascii")

    document_reference = {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "11506-3",
                "display": "Progress note"
            }],
            "text": "AI Voice Assistant Visit Note"
        },
        "subject": {"reference": f"Patient/{pid}"},
        "date": now_iso,
        "description": "Auto-generated visit note from AI health voice assistant call",
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "data": encoded,
                "title": f"Visit Note — {now_iso[:10]}"
            }
        }]
    }

    client = _get_client()
    created = (
        _fhir(client)
        .create(
            parent=FHIR_BASE,
            type="DocumentReference",
            body=document_reference,
        )
        .execute()
    )
    print(f"📝 Visit note written to FHIR for patient {pid}: {created.get('id', 'unknown id')}")
    return created


# ── Context-cache (TTL = 5 min, keyed by patient_id) ─────────────────────────

_CACHE_TTL   = 300
_cache_lock  = threading.Lock()
# { patient_id: (context_str, timestamp) }
_cache: Dict[str, Tuple[str, float]] = {}


def _is_cache_fresh(patient_id: str) -> bool:
    entry = _cache.get(patient_id)
    return bool(entry) and (time.monotonic() - entry[1] < _CACHE_TTL)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _name(patient: Dict) -> str:
    names = patient.get("name", [{}])
    n = names[0]
    given = " ".join(n.get("given", []))
    family = n.get("family", "")
    return f"{given} {family}".strip()


def _age(patient: Dict) -> str:
    dob = patient.get("birthDate", "")
    if not dob:
        return "unknown"
    birth = date.fromisoformat(dob)
    today = date.today()
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return str(age)


def _format_context(
    patient: Dict,
    conditions: List,
    medications: List,
    observations: List,
    allergies: List,
    appointments: List,
) -> str:
    lines = []

    # Demographics
    lines.append("=== PATIENT PROFILE ===")
    lines.append(f"Name       : {_name(patient)}")
    lines.append(f"Age        : {_age(patient)} years  (DOB: {patient.get('birthDate', 'N/A')})")
    lines.append(f"Gender     : {patient.get('gender', 'N/A').capitalize()}")
    telecom = patient.get("telecom", [])
    phone = next((t["value"] for t in telecom if t.get("system") == "phone"), "N/A")
    lines.append(f"Phone      : {phone}")

    # Conditions
    lines.append("\n=== ACTIVE CONDITIONS ===")
    if conditions:
        for c in conditions:
            text  = c.get("code", {}).get("text", "Unknown condition")
            onset = c.get("onsetDateTime", "unknown onset")
            note  = c.get("note", [{}])[0].get("text", "")
            lines.append(f"• {text}  (since {onset})")
            if note:
                lines.append(f"  Note: {note}")
    else:
        lines.append("  None recorded.")

    # Medications
    lines.append("\n=== CURRENT MEDICATIONS ===")
    if medications:
        for m in medications:
            name   = m.get("medicationCodeableConcept", {}).get("text", "Unknown")
            dose   = m.get("dosage", [{}])[0].get("text", "")
            reason = m.get("reasonCode", [{}])[0].get("text", "")
            lines.append(f"• {name}  —  {dose}  (for {reason})")
    else:
        lines.append("  None recorded.")

    # Lab Results
    lines.append("\n=== RECENT LAB RESULTS ===")
    if observations:
        for o in observations:
            name = o.get("code", {}).get("coding", [{}])[0].get("display", "Unknown")
            date_str = o.get("effectiveDateTime", "")[:10]

            val_q = o.get("valueQuantity", {})
            if val_q:
                value = f"{val_q.get('value')} {val_q.get('unit', '')}".strip()
            else:
                comps = o.get("component", [])
                parts = []
                for comp in comps:
                    disp = comp.get("code", {}).get("coding", [{}])[0].get("display", "")
                    v    = comp.get("valueQuantity", {}).get("value", "")
                    u    = comp.get("valueQuantity", {}).get("unit", "")
                    parts.append(f"{disp}: {v} {u}")
                value = ", ".join(parts)

            note = o.get("note", [{}])[0].get("text", "") if o.get("note") else ""
            lines.append(f"• {name} ({date_str}): {value}")
            if note:
                lines.append(f"  → {note}")
    else:
        lines.append("  None recorded.")

    # Allergies
    lines.append("\n=== ALLERGIES ===")
    if allergies:
        for a in allergies:
            allergen  = a.get("code", {}).get("text", "Unknown")
            reactions = []
            for r in a.get("reaction", []):
                for m in r.get("manifestation", []):
                    reactions.append(m.get("coding", [{}])[0].get("display", ""))
            reaction_str = ", ".join(filter(None, reactions)) or "unspecified"
            lines.append(f"• {allergen}  →  Reaction: {reaction_str}")
    else:
        lines.append("  None recorded.")

    # Upcoming Appointments
    lines.append("\n=== UPCOMING APPOINTMENTS ===")
    if appointments:
        for appt in appointments:
            desc  = appt.get("description", "Appointment")
            start = appt.get("start", "")[:16].replace("T", " at ")
            lines.append(f"• {desc}  on  {start}")
    else:
        lines.append("  None scheduled.")

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def build_patient_context(
    patient_id: Optional[str] = None,
    force_refresh: bool = False,
) -> str:
    """
    Returns a structured text summary of the patient's medical history.

    patient_id: which patient to fetch.  Falls back to PATIENT_ID env var
                when not supplied (useful for standalone testing).
    force_refresh: bypass the per-patient 5-minute cache.

    Results are cached per patient_id for CACHE_TTL seconds so a new
    WebSocket connection for the same patient within that window doesn't
    hammer FHIR again.
    """
    pid = (patient_id or _DEFAULT_PATIENT_ID).strip()
    if not pid:
        raise ValueError("patient_id is required")

    if not force_refresh and _is_cache_fresh(pid):
        return _cache[pid][0]

    with _cache_lock:
        if not force_refresh and _is_cache_fresh(pid):
            return _cache[pid][0]

        patient, conditions, medications, observations, allergies, appointments = (
            fetch_all_parallel(pid)
        )
        context = _format_context(
            patient, conditions, medications, observations, allergies, appointments
        )
        _cache[pid] = (context, time.monotonic())

    return context


if __name__ == "__main__":
    import sys, time as t
    pid = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_PATIENT_ID
    start = t.perf_counter()
    print(build_patient_context(patient_id=pid, force_refresh=True))
    print(f"\n⏱  Fetched in {t.perf_counter() - start:.2f}s")