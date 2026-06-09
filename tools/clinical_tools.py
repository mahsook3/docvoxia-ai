"""
tools/clinical_tools.py
------------------------
ADK-compatible clinical NLP tool functions.

Tools:
  - extract_medical_terms    : extract structured clinical entities from free text
  - check_drug_interactions  : flag potential drug-drug / drug-allergy conflicts
  - generate_soap_note       : format a SOAP clinical note from structured data
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# extract_medical_terms
# ---------------------------------------------------------------------------

def extract_medical_terms(text: str) -> Dict[str, Any]:
    """
    Extract structured clinical entities from free-form clinical text using
    Google Cloud Healthcare Natural Language API (or a local heuristic fallback).

    Entities extracted:
      - conditions   : diagnoses and medical history items
      - symptoms     : presenting complaints with duration / severity where stated
      - medications  : drug names with dose, route, frequency if mentioned
      - observations : numeric findings (vitals, lab values)
      - diagnoses    : differential or confirmed diagnoses

    Args:
        text: Raw clinical text (transcript excerpt, doctor note, patient description).

    Returns:
        Dict with keys: conditions, symptoms, medications, observations, diagnoses.
        Each value is a list of dicts with entity-specific fields.
    """
    if not text or not text.strip():
        return _empty_terms()

    # ── Try Cloud Healthcare NL API first ────────────────────────────────────
    try:
        return _extract_via_healthcare_nlp(text)
    except Exception as exc:
        logger.warning("Healthcare NLP API unavailable (%s); using heuristic fallback.", exc)

    # ── Heuristic fallback (regex-based) ─────────────────────────────────────
    return _extract_heuristic(text)


def _extract_via_healthcare_nlp(text: str) -> Dict[str, Any]:
    """Call Google Cloud Healthcare Natural Language API."""
    from google.cloud import healthcare_v1

    project   = os.environ.get("GCP_PROJECT_ID", "docvoxia")
    location  = os.environ.get("GCP_LOCATION", "us-central1")
    dataset   = os.environ.get("HEALTHCARE_DATASET", "clinical-dataset")

    client = healthcare_v1.CloudHealthcareClient()
    name   = f"projects/{project}/locations/{location}/datasets/{dataset}"

    response = client.analyze_entities(
        request={
            "parent":        name,
            "nlp_service":   "projects/{}/locations/{}/services/nlp".format(project, location),
            "document_content": text,
            "encoding_type": "UTF8",
            "alternative_output_format": "FHIR_BUNDLE",
            "licensed_vocabularies": ["ICD10CM", "RXNORM"],
        }
    )

    result = _empty_terms()

    for entity in response.entity_mentions:
        label = entity.text.content
        kind  = entity.type_

        if kind in ("PROBLEM", "DISEASE_DISORDER"):
            result["conditions"].append({"name": label, "status": "active"})
        elif kind == "SIGN_SYMPTOM":
            result["symptoms"].append({"name": label, "duration": None, "severity": None})
        elif kind == "MEDICATION":
            result["medications"].append({"name": label, "dose": None, "route": None, "frequency": None})
        elif kind in ("LAB_VALUE", "VITAL_SIGN"):
            result["observations"].append({"name": label, "value": None, "unit": None})

    return result


def _extract_heuristic(text: str) -> Dict[str, Any]:
    """
    Very lightweight regex / keyword heuristic.
    Useful when GCP credentials are not available (local dev / tests).
    """
    result = _empty_terms()

    # Symptom patterns — "complains of X", "presents with X", "has X"
    symptom_patterns = [
        r"(?:complains? of|presents? with|suffering from|reports?|has)\s+([^,.;]+)",
        r"(?:chief complaint|c/c|cc)[:\s]+([^,.;\n]+)",
    ]
    for pat in symptom_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            name = m.group(1).strip()
            if name and len(name) < 120:
                result["symptoms"].append({"name": name, "duration": None, "severity": None})

    # Duration pattern — "for X days/weeks/months"
    duration_pat = re.compile(r"for\s+(\d+\s+(?:day|week|month|year)s?)", re.IGNORECASE)
    if result["symptoms"] and duration_pat.search(text):
        duration = duration_pat.search(text).group(1)
        for s in result["symptoms"]:
            if s["duration"] is None:
                s["duration"] = duration

    # Medication patterns — "prescribed X", "take X", "start X"
    med_patterns = [
        r"(?:prescribed?|take|start|given|on)\s+([\w\s]+ \d+\s*mg[^,.;]*)",
        r"(?:tab|cap|inj|syrup)\s+([\w\s]+\d+\s*mg[^,.;]*)",
    ]
    for pat in med_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            name = m.group(1).strip()
            if name and len(name) < 80:
                result["medications"].append({"name": name, "dose": None, "route": None, "frequency": None})

    # Vitals / observations — "BP 120/80", "temp 38.5", "SpO2 98%"
    obs_patterns = [
        (r"BP[:\s]+(\d{2,3}/\d{2,3})",                      "Blood Pressure",   "mmHg"),
        (r"(?:temp|temperature)[:\s]+([\d.]+)\s*°?[CF]?",   "Temperature",      "°C"),
        (r"(?:SpO2|spo2|O2 sat)[:\s]+([\d.]+)\s*%?",        "SpO2",             "%"),
        (r"(?:pulse|heart rate|HR)[:\s]+(\d+)",              "Heart Rate",       "bpm"),
        (r"(?:RR|resp rate)[:\s]+(\d+)",                     "Respiratory Rate", "/min"),
        (r"(?:weight|wt)[:\s]+([\d.]+)\s*kg",                "Weight",           "kg"),
        (r"(?:height|ht)[:\s]+([\d.]+)\s*cm",                "Height",           "cm"),
    ]
    for pat, name, unit in obs_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["observations"].append({"name": name, "value": m.group(1), "unit": unit})

    # Diagnosis patterns — "diagnosis: X", "impression: X", "likely X"
    diag_patterns = [
        r"(?:diagnosis|impression|assessment|dx)[:\s]+([^,.;\n]+)",
        r"likely\s+(?:a\s+|an\s+)?([^,.;\n]{5,60})",
    ]
    for pat in diag_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            name = m.group(1).strip()
            if name and len(name) < 80:
                result["diagnoses"].append({"name": name, "confidence": "moderate"})

    return result


def _empty_terms() -> Dict[str, Any]:
    return {
        "conditions":   [],
        "symptoms":     [],
        "medications":  [],
        "observations": [],
        "diagnoses":    [],
    }


# ---------------------------------------------------------------------------
# check_drug_interactions
# ---------------------------------------------------------------------------

def check_drug_interactions(
    medications: List[Dict[str, Any]],
    allergies: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Check a list of medications for potential drug-drug interactions
    and drug-allergy conflicts.

    Args:
        medications: List of medication dicts with at least a "name" key.
                     Example: [{"name": "Warfarin", "dose": "5mg"}, ...]
        allergies:   Optional list of allergy strings (drug names or classes).

    Returns:
        Dict with keys:
          - "interactions" : list of interaction warning dicts
              { "drugs": [str, str], "severity": "high|moderate|low", "description": str }
          - "allergy_conflicts" : list of conflict dicts
              { "drug": str, "allergen": str, "description": str }
          - "safe": bool  — True if no high-severity issues found
    """
    allergies = allergies or []
    med_names = [m.get("name", "") for m in medications if m.get("name")]

    interactions:      List[Dict[str, Any]] = []
    allergy_conflicts: List[Dict[str, Any]] = []

    # ── Known high-risk pairs (a minimal curated list for safety ─────────────
    HIGH_RISK_PAIRS: List[tuple] = [
        ("warfarin",     "aspirin",       "Increased bleeding risk"),
        ("warfarin",     "ibuprofen",     "Increased anticoagulation + GI bleed risk"),
        ("warfarin",     "naproxen",      "Increased anticoagulation + GI bleed risk"),
        ("metformin",    "contrast",      "Risk of lactic acidosis"),
        ("ssri",         "tramadol",      "Serotonin syndrome risk"),
        ("maoi",         "ssri",          "Potentially fatal serotonin syndrome"),
        ("maoi",         "tramadol",      "Serotonin syndrome risk"),
        ("maoi",         "meperidine",    "Serotonin syndrome risk"),
        ("digoxin",      "amiodarone",    "Digoxin toxicity — dose reduction needed"),
        ("simvastatin",  "amiodarone",    "Myopathy / rhabdomyolysis risk"),
        ("clopidogrel",  "omeprazole",    "Reduced antiplatelet effect"),
        ("lithium",      "nsaid",         "Lithium toxicity risk"),
        ("lithium",      "ibuprofen",     "Lithium toxicity risk"),
        ("quinolone",    "antacid",       "Reduced quinolone absorption"),
        ("methotrexate", "nsaid",         "Methotrexate toxicity risk"),
    ]

    MODERATE_RISK_PAIRS: List[tuple] = [
        ("ace inhibitor", "potassium",    "Hyperkalaemia risk"),
        ("beta blocker",  "calcium channel blocker", "Additive cardiac depression"),
        ("alcohol",       "metronidazole","Disulfiram-like reaction"),
        ("alcohol",       "tinidazole",   "Disulfiram-like reaction"),
        ("ciprofloxacin", "theophylline", "Theophylline toxicity"),
    ]

    def _match(a: str, b: str, x: str, y: str) -> bool:
        return (x in a and y in b) or (y in a and x in b)

    lower_names = [n.lower() for n in med_names]

    for i, a in enumerate(lower_names):
        for j, b in enumerate(lower_names):
            if j <= i:
                continue
            for x, y, desc in HIGH_RISK_PAIRS:
                if _match(a, b, x, y):
                    interactions.append({
                        "drugs":       [med_names[i], med_names[j]],
                        "severity":    "high",
                        "description": desc,
                    })
            for x, y, desc in MODERATE_RISK_PAIRS:
                if _match(a, b, x, y):
                    interactions.append({
                        "drugs":       [med_names[i], med_names[j]],
                        "severity":    "moderate",
                        "description": desc,
                    })

    # ── Allergy conflicts ─────────────────────────────────────────────────────
    # Penicillin cross-reactivity with cephalosporins (~2-3%)
    CROSS_REACT = {
        "penicillin":  ["amoxicillin", "ampicillin", "cephalosporin", "ceftriaxone",
                        "cefazolin", "cephalexin"],
        "sulfa":       ["sulfamethoxazole", "trimethoprim-sulfamethoxazole",
                        "furosemide", "thiazide"],
        "aspirin":     ["ibuprofen", "naproxen", "diclofenac", "nsaid"],
    }

    lower_allergies = [a.lower() for a in allergies]

    for allergy in lower_allergies:
        for med in lower_names:
            if allergy in med or med in allergy:
                allergy_conflicts.append({
                    "drug":        med,
                    "allergen":    allergy,
                    "description": f"Direct match: patient allergic to {allergy}",
                })
            for allergen_class, related in CROSS_REACT.items():
                if allergen_class in allergy:
                    for related_drug in related:
                        if related_drug in med:
                            allergy_conflicts.append({
                                "drug":        med,
                                "allergen":    allergy,
                                "description": f"Possible cross-reactivity with {allergen_class}",
                            })

    has_high = any(i["severity"] == "high" for i in interactions)
    safe = not has_high and not allergy_conflicts

    return {
        "interactions":       interactions,
        "allergy_conflicts":  allergy_conflicts,
        "safe":               safe,
    }


# ---------------------------------------------------------------------------
# generate_soap_note
# ---------------------------------------------------------------------------

def generate_soap_note(
    patient_name: str,
    chief_complaint: str,
    subjective: str,
    objective: str,
    assessment: str,
    plan: str,
    provider_name: Optional[str] = None,
    encounter_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Format a structured SOAP note from discrete clinical components.

    Args:
        patient_name:    Full name of the patient.
        chief_complaint: One-line chief complaint.
        subjective:      History of present illness (HPI), ROS, PMH, medications, allergies.
        objective:       Physical exam findings, vitals, relevant lab values.
        assessment:      Diagnosis / differential diagnoses with reasoning.
        plan:            Treatment plan: medications, referrals, follow-up.
        provider_name:   Optional signing provider name.
        encounter_date:  Optional date string (ISO or human-readable).

    Returns:
        Dict with keys:
          - "soap_note"  : str — formatted note text
          - "sections"   : dict — individual S/O/A/P sections
    """
    import datetime

    date_str = encounter_date or datetime.date.today().isoformat()

    note_lines = [
        f"SOAP NOTE",
        f"{'=' * 60}",
        f"Patient       : {patient_name}",
        f"Date          : {date_str}",
    ]
    if provider_name:
        note_lines.append(f"Provider      : {provider_name}")
    note_lines += [
        f"Chief Complaint: {chief_complaint}",
        "",
        "SUBJECTIVE",
        "-" * 40,
        subjective.strip(),
        "",
        "OBJECTIVE",
        "-" * 40,
        objective.strip(),
        "",
        "ASSESSMENT",
        "-" * 40,
        assessment.strip(),
        "",
        "PLAN",
        "-" * 40,
        plan.strip(),
        "",
        f"{'=' * 60}",
    ]
    if provider_name:
        note_lines.append(f"Electronically signed by: {provider_name}")
    note_lines.append(f"Date/Time: {date_str}")

    soap_text = "\n".join(note_lines)

    return {
        "soap_note": soap_text,
        "sections": {
            "subjective": subjective.strip(),
            "objective":  objective.strip(),
            "assessment": assessment.strip(),
            "plan":       plan.strip(),
        },
    }