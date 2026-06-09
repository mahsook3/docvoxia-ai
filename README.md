# Healthcare AI — Multi-Agent Backend

> Google ADK-powered multi-agent system for patient care, clinical assistance, prescription management, and FHIR-based healthcare data exchange.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Setup & Running](#setup--running)
- [API Reference](#api-reference)
  - [System](#system)
  - [ASR — Speech-to-Text](#asr--speech-to-text)
  - [TTS — Text-to-Speech](#tts--text-to-speech)
  - [Patients / FHIR](#patients--fhir)
  - [Sessions](#sessions)
  - [Clinical Assistant](#clinical-assistant)
  - [Prescription](#prescription)
- [Typical End-to-End Flow](#typical-end-to-end-flow)
- [Environment Variables](#environment-variables)

---

## Overview

This backend orchestrates four specialised Google ADK agents:

| Agent | Responsibility |
|---|---|
| `PatientCareAgent` | Multilingual intake, registration, appointment flows |
| `ClinicalAssistantAgent` | Doctor support — symptom/diagnosis/medication extraction, SOAP notes |
| `PrescriptionAgent` | Post-consult prescriptions, follow-up care plans, FHIR resources |
| `HealthcareDataAgent` | FHIR data exchange with Google Cloud Healthcare API |

---

## Architecture

```
Client (Web / Mobile / Voice)
        │
        ▼
   FastAPI Backend  (main.py)
        │
   ┌────┴─────────────────────────────────────────┐
   │  Routers                                     │
   │  /asr  /tts  /patients  /sessions            │
   │  /clinical  /prescription                    │
   └────┬─────────────────────────────────────────┘
        │
   ┌────┴──────────────────────────────────────┐
   │  ADK Agents                               │
   │  PatientCareAgent ──► ClinicalAgent       │
   │  PrescriptionAgent ◄── HealthcareAgent    │
   └────┬──────────────────────────────────────┘
        │
   Google Cloud Services
   ├── Speech-to-Text v2 (Chirp 3)
   ├── Text-to-Speech
   ├── Translation API
   └── Cloud Healthcare FHIR API
```

---

## Setup & Running

```bash
# Install dependencies
pip install -r requirements.txt

# Set required environment variables (see section below)
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export ADK_MODEL=gemini-2.5-flash

# Start the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API docs available at: `http://localhost:8000/docs`

---

## API Reference

### System

#### `GET /health`

Health check — confirms the service is running and lists active agents.

**Response `200 OK`**
```json
{
  "status": "ok",
  "version": "2.0.0",
  "agents": [
    "PatientCareAgent",
    "ClinicalAssistantAgent",
    "PrescriptionAgent",
    "HealthcareDataAgent"
  ]
}
```

#### `GET /`

Service root with navigation links.

**Response `200 OK`**
```json
{
  "service": "Healthcare AI Backend",
  "docs": "/docs",
  "health": "/health"
}
```

---

### ASR — Speech-to-Text

Powered by **Google Cloud Speech-to-Text v2 (Chirp 3)** with automatic language detection and speaker diarization.

#### `POST /transcribe`

Transcribe an uploaded audio file (any format — auto-detected).

**Request** — multipart/form-data

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File | ✅ | Audio file (mp3, wav, ogg, flac, webm, etc.) |
| `min_speakers` | int | ❌ | Minimum speakers for diarization (default: 1) |
| `max_speakers` | int | ❌ | Maximum speakers for diarization (default: 6) |

**Example (curl)**
```bash
curl -X POST http://localhost:8000/transcribe \
  -F "file=@consultation.mp3" \
  -F "min_speakers=2" \
  -F "max_speakers=2"
```

**Response `200 OK`**
```json
{
  "transcript": "Doctor: How long have you had this pain? Patient: About three days now, it started suddenly.",
  "utterances": [
    { "speaker": "A", "text": "How long have you had this pain?" },
    { "speaker": "B", "text": "About three days now, it started suddenly." }
  ],
  "detected_languages": ["en-US"],
  "speakers": ["A", "B"],
  "speaker_count": 2,
  "filename": "consultation.mp3"
}
```

---

#### `POST /transcribe-bytes`

Transcribe raw audio provided as a base64-encoded string. Useful for browser/mobile clients that send audio blobs directly.

**Request Body**
```json
{
  "audio_base64": "SUQzBAAAAAAA...(base64 encoded audio bytes)",
  "filename": "voice-note.webm",
  "min_speakers": 1,
  "max_speakers": 3
}
```

**Response `200 OK`**
```json
{
  "transcript": "I have been experiencing chest pain and shortness of breath for the past two days.",
  "utterances": [
    {
      "speaker": "A",
      "text": "I have been experiencing chest pain and shortness of breath for the past two days."
    }
  ],
  "detected_languages": ["en-US"],
  "speakers": ["A"],
  "speaker_count": 1,
  "filename": "voice-note.webm"
}
```

---

### TTS — Text-to-Speech

Backed by **Google Cloud Text-to-Speech**. Returns MP3 audio as a base64-encoded string.

#### `POST /synthesize`

**Request Body**
```json
{
  "text": "Your appointment has been confirmed for tomorrow at 10 AM.",
  "language_code": "en-US",
  "voice_name": "en-US-Journey-F",
  "speaking_rate": 1.0,
  "pitch": 0.0
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | ✅ | Text to synthesize |
| `language_code` | string | ❌ | BCP-47 language tag (default: `"en-US"`) |
| `voice_name` | string | ❌ | Specific voice e.g. `"en-US-Journey-F"` |
| `speaking_rate` | float | ❌ | Speed multiplier 0.25–4.0 (default: `1.0`) |
| `pitch` | float | ❌ | Semitone adjustment -20.0–20.0 (default: `0.0`) |

**Response `200 OK`**
```json
{
  "audio_base64": "//NExAANqAIIAUAAAP...(base64 MP3 bytes)",
  "language_code": "en-US",
  "voice_name": "en-US-Journey-F"
}
```

**Multilingual example (Tamil)**
```json
{
  "text": "உங்கள் சந்திப்பு நாளை காலை 10 மணிக்கு உறுதி செய்யப்பட்டுள்ளது.",
  "language_code": "ta-IN",
  "voice_name": "ta-IN-Standard-A"
}
```

---

### Patients / FHIR

Direct FHIR Patient resource management via Google Cloud Healthcare API.

#### `GET /patients`

List all patients in the FHIR store.

| Query Param | Type | Description |
|---|---|---|
| `limit` | int (1–500) | Max number of patients to return |

**Example**
```
GET /patients?limit=20
```

**Response `200 OK`**
```json
{
  "patients": [
    {
      "resourceType": "Patient",
      "id": "patient-001",
      "name": [{ "use": "official", "given": ["Arjun"], "family": "Sharma" }],
      "birthDate": "1985-03-22",
      "gender": "male",
      "telecom": [{ "system": "phone", "value": "+91-9876543210", "use": "mobile" }]
    }
  ]
}
```

---

#### `GET /patients/{patient_id}`

Fetch a single Patient resource by FHIR ID.

**Example**
```
GET /patients/patient-001
```

**Response `200 OK`**
```json
{
  "resourceType": "Patient",
  "id": "patient-001",
  "name": [{ "use": "official", "given": ["Arjun"], "family": "Sharma" }],
  "birthDate": "1985-03-22",
  "gender": "male",
  "telecom": [{ "system": "phone", "value": "+91-9876543210", "use": "mobile" }]
}
```

**Response `404 Not Found`**
```json
{ "detail": "Patient 'patient-001' not found." }
```

---

#### `POST /patients`

Register a new patient in the FHIR store.

**Request Body**
```json
{
  "given_name": "Priya",
  "family_name": "Nair",
  "birth_date": "1992-07-15",
  "gender": "female",
  "phone": "+91-9988776655"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `given_name` | string | ✅ | First name |
| `family_name` | string | ✅ | Last name |
| `birth_date` | string | ✅ | ISO date e.g. `"1992-07-15"` |
| `gender` | string | ✅ | `"male"` \| `"female"` \| `"other"` \| `"unknown"` |
| `phone` | string | ❌ | Phone number |

**Response `201 Created`**
```json
{
  "resourceType": "Patient",
  "id": "a3f2c1b8-9d4e-4f7a-b6e5-1234567890ab",
  "name": [{ "use": "official", "given": ["Priya"], "family": "Nair" }],
  "birthDate": "1992-07-15",
  "gender": "female",
  "telecom": [{ "system": "phone", "value": "+91-9988776655", "use": "mobile" }]
}
```

---

#### `GET /patients/{patient_id}/context`

Fetch a structured full medical history summary for a patient — demographics, active conditions, medications, observations, allergies, and upcoming appointments.

| Query Param | Type | Description |
|---|---|---|
| `force_refresh` | bool | Bypass the 5-minute cache (default: `false`) |

**Example**
```
GET /patients/patient-001/context?force_refresh=false
```

**Response `200 OK`**
```json
{
  "patient_id": "patient-001",
  "context": "Patient: Arjun Sharma | DOB: 1985-03-22 | Gender: Male\n\nActive Conditions:\n- Type 2 Diabetes Mellitus (since 2019)\n- Hypertension (since 2021)\n\nCurrent Medications:\n- Metformin 500mg twice daily\n- Amlodipine 5mg once daily\n\nRecent Observations:\n- Blood Glucose: 142 mg/dL (2024-11-01)\n- BP: 138/88 mmHg (2024-11-01)\n\nAllergies:\n- Penicillin (anaphylaxis)\n\nUpcoming Appointments:\n- 2024-12-10 10:00 AM — Endocrinology Follow-up"
}
```

---

#### `POST /patients/{patient_id}/visit-note`

Persist a clinical visit note to FHIR as a DocumentReference resource.

**Request Body**
```json
{
  "note_text": "S: Patient presents with fatigue and increased thirst for 2 weeks. O: BP 138/88, FBS 142 mg/dL. A: Poorly controlled T2DM. P: Increase Metformin to 1000mg BD. Follow up in 4 weeks."
}
```

**Response `201 Created`**
```json
{
  "status": "created",
  "resource": {
    "resourceType": "DocumentReference",
    "id": "docref-7f3a2b1c",
    "status": "current",
    "subject": { "reference": "Patient/patient-001" },
    "content": [
      {
        "attachment": {
          "contentType": "text/plain",
          "data": "UzogUGF0aWVudCBwcmVzZW50cy4uLg=="
        }
      }
    ]
  }
}
```

---

### Sessions

Manages conversation sessions. Each session tracks a patient intake workflow, accumulated clinical data, and conversation history. Sessions expire after **1 hour** of inactivity.

#### `GET /session-types`

List all available session types (built-in + custom).

**Response `200 OK`**
```json
{
  "session_types": [
    {
      "type_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "OPD Prescription",
      "description": "Outpatient consultation leading to a prescription.",
      "required_fields": ["chief_complaint", "symptoms", "duration", "allergies"]
    },
    {
      "type_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "name": "Triage Assessment",
      "description": "Emergency triage to determine acuity level.",
      "required_fields": ["chief_complaint", "vitals", "pain_scale"]
    },
    {
      "type_id": "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
      "name": "Follow-up Visit",
      "description": "Post-treatment follow-up for chronic condition management.",
      "required_fields": ["previous_diagnosis", "current_symptoms", "medications"]
    },
    {
      "type_id": "6ba7b812-9dad-11d1-80b4-00c04fd430c8",
      "name": "Lab Result Review",
      "description": "Doctor reviews lab results with patient.",
      "required_fields": ["lab_type", "results", "interpretation"]
    }
  ]
}
```

---

#### `POST /session-types`

Register a custom session type.

**Request Body**
```json
{
  "name": "Vaccination Counselling",
  "description": "Counsel and schedule patient vaccinations.",
  "required_fields": ["age", "vaccination_history", "allergies", "travel_history"]
}
```

**Response `201 Created`**
```json
{
  "type_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "name": "Vaccination Counselling"
}
```

---

#### `POST /sessions`

Create a new session. Returns a `user_id` that is used as the session key for all subsequent calls.

**Request Body**
```json
{
  "session_type_id": "550e8400-e29b-41d4-a716-446655440000",
  "patient_id": "patient-001"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `session_type_id` | string | ✅ | ID from `GET /session-types` |
| `patient_id` | string | ❌ | Pre-link to an existing FHIR patient |

**Response `201 Created`**
```json
{
  "user_id": "3d6f4f30-1b2c-4e5a-9f8d-7a1b2c3d4e5f",
  "session_type": {
    "type_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "OPD Prescription",
    "description": "Outpatient consultation leading to a prescription.",
    "required_fields": ["chief_complaint", "symptoms", "duration", "allergies"]
  },
  "patient_id": "patient-001",
  "status": "created"
}
```

---

#### `GET /sessions/{user_id}`

Fetch the current state of a session.

**Response `200 OK`**
```json
{
  "user_id": "3d6f4f30-1b2c-4e5a-9f8d-7a1b2c3d4e5f",
  "session_type_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_type": { "name": "OPD Prescription", "required_fields": ["chief_complaint", "symptoms", "duration", "allergies"] },
  "history": [
    { "role": "user", "content": "I have a headache and fever for 3 days." },
    { "role": "assistant", "content": "I'm sorry to hear that. Are you allergic to any medications?" }
  ],
  "medical_terms": {
    "conditions": [],
    "medications": [],
    "observations": [],
    "symptoms": [{ "name": "headache", "duration": "3 days", "severity": null }, { "name": "fever", "duration": "3 days", "severity": null }],
    "diagnoses": []
  },
  "patient_id": "patient-001",
  "complete": false,
  "created_at": 1700000000.0,
  "updated_at": 1700000120.0
}
```

---

#### `DELETE /sessions/{user_id}`

End and permanently delete a session.

**Response `200 OK`**
```json
{
  "status": "deleted",
  "user_id": "3d6f4f30-1b2c-4e5a-9f8d-7a1b2c3d4e5f"
}
```

---

#### `POST /sessions/{user_id}/message`

Send a patient message to the **PatientCareAgent**. The agent responds conversationally, collects required fields, and signals `complete: true` when intake is finished.

**Request Body**
```json
{
  "message": "I have had a severe headache and fever for 3 days. I am not allergic to any medicines."
}
```

**Response `200 OK` — intake in progress**
```json
{
  "reply": "Thank you for sharing that. Could you tell me how old you are and whether the fever has been consistent or comes and goes?",
  "complete": false,
  "session": {
    "user_id": "3d6f4f30-1b2c-4e5a-9f8d-7a1b2c3d4e5f",
    "complete": false,
    "history": [
      { "role": "user", "content": "I have had a severe headache and fever for 3 days. I am not allergic to any medicines." },
      { "role": "assistant", "content": "Thank you for sharing that. Could you tell me how old you are and whether the fever has been consistent or comes and goes?" }
    ]
  }
}
```

**Response `200 OK` — intake complete**
```json
{
  "reply": "Thank you! I've collected all the information needed. The doctor will be with you shortly.",
  "complete": true,
  "session": {
    "user_id": "3d6f4f30-1b2c-4e5a-9f8d-7a1b2c3d4e5f",
    "complete": true
  }
}
```

---

### Clinical Assistant

Backed by **ClinicalAssistantAgent**. These endpoints are typically called during or after a doctor–patient consultation.

#### `POST /clinical/{user_id}/check-completeness`

Analyse a clinical transcript or query for completeness. Extracts structured medical terms and returns a `complete` flag.

**Request Body**
```json
{
  "query": "Doctor: The patient has a 3-day history of high-grade fever (102°F), severe bifrontal headache, and myalgia. No rash. No neck stiffness. No known drug allergies. Plan to start empirical Paracetamol 500mg TDS and do CBC and Dengue NS1."
}
```

**Response `200 OK`**
```json
{
  "complete": true,
  "medical_terms": {
    "conditions": [],
    "medications": [
      { "name": "Paracetamol", "dose": "500mg", "route": "oral", "frequency": "three times daily" }
    ],
    "observations": [
      { "name": "Temperature", "value": "102", "unit": "°F" }
    ],
    "symptoms": [
      { "name": "fever", "duration": "3 days", "severity": "high-grade" },
      { "name": "headache", "duration": "3 days", "severity": "severe" },
      { "name": "myalgia", "duration": "3 days", "severity": null }
    ],
    "diagnoses": [
      { "name": "Dengue fever (suspected)", "confidence": "moderate" }
    ]
  }
}
```

---

#### `POST /clinical/{user_id}/clarify`

Submit a clarification answer from the doctor or patient and re-evaluate completeness.

**Request Body**
```json
{
  "clarification": "The patient also mentioned mild nausea but no vomiting. No travel history. Platelet count not yet done."
}
```

**Response `200 OK`**
```json
{
  "complete": false,
  "medical_terms": {
    "conditions": [],
    "medications": [
      { "name": "Paracetamol", "dose": "500mg", "route": "oral", "frequency": "three times daily" }
    ],
    "observations": [
      { "name": "Temperature", "value": "102", "unit": "°F" }
    ],
    "symptoms": [
      { "name": "fever", "duration": "3 days", "severity": "high-grade" },
      { "name": "headache", "duration": "3 days", "severity": "severe" },
      { "name": "myalgia", "duration": "3 days", "severity": null },
      { "name": "nausea", "duration": null, "severity": "mild" }
    ],
    "diagnoses": [
      { "name": "Dengue fever (suspected)", "confidence": "moderate" }
    ]
  }
}
```

---

#### `GET /clinical/{user_id}/clarifying-question`

Ask the ClinicalAssistantAgent what the single most important clarifying question is to ask next.

**Response `200 OK`**
```json
{
  "clarifying_question": "Has the patient noticed any bleeding manifestations such as gum bleeding, skin rashes, or blood in urine or stool?"
}
```

---

#### `GET /clinical/{user_id}/summary`

Generate a formatted clinical summary suitable for the medical record.

**Response `200 OK`**
```json
{
  "formatted_info": "CLINICAL SUMMARY\n\nChief Complaint: Fever, headache, and body aches for 3 days.\n\nHistory of Present Illness:\nA patient presents with a 3-day history of high-grade fever (102°F), severe bifrontal headache, and myalgia. Associated mild nausea. No vomiting, rash, neck stiffness, or bleeding manifestations. No recent travel history.\n\nAllergies: None known.\n\nAssessment:\nClinical presentation consistent with suspected Dengue fever. Awaiting CBC and Dengue NS1 antigen results.\n\nPlan:\n- Paracetamol 500mg three times daily for fever management\n- Investigations: CBC, Dengue NS1 antigen\n- Adequate oral hydration\n- Return immediately if any bleeding, severe abdominal pain, or rapid deterioration"
}
```

---

#### `POST /clinical/{user_id}/soap-note`

Generate a SOAP note. Optionally persist it to FHIR as a DocumentReference.

**Request Body**
```json
{
  "persist": true,
  "patient_id": "patient-001"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `persist` | bool | ❌ | Write note to FHIR if `true` (default: `false`) |
| `patient_id` | string | ❌ | Required if `persist: true` |

**Response `201 Created`**
```json
{
  "soap_note": "S (Subjective):\nPatient reports 3-day history of high-grade fever (102°F), severe bifrontal headache, myalgia, and mild nausea. No vomiting, rash, or bleeding. No known drug allergies.\n\nO (Objective):\nTemp: 102°F. Investigations pending: CBC, Dengue NS1 antigen.\n\nA (Assessment):\nSuspected Dengue fever.\n\nP (Plan):\n1. Paracetamol 500mg TDS (oral) for symptomatic fever relief.\n2. Order CBC and Dengue NS1 antigen.\n3. Advise high oral fluid intake.\n4. Return precautions for bleeding symptoms or clinical deterioration.",
  "persisted": true,
  "fhir_resource": {
    "resourceType": "DocumentReference",
    "id": "docref-9a1b2c3d",
    "status": "current",
    "subject": { "reference": "Patient/patient-001" }
  }
}
```

---

### Prescription

Backed by **PrescriptionAgent**. Generates prescriptions with a human-in-the-loop approval checkpoint before FHIR resources are written.

#### `POST /prescription/{user_id}/generate`

Generate a full prescription, follow-up instructions, patient-friendly summary, and FHIR MedicationRequest list for a completed session. The session must have `complete: true`.

**Request Body**
```json
{
  "target_language": "en",
  "require_approval": true
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `target_language` | string | ❌ | BCP-47 code for patient-facing output (default: `"en"`) |
| `require_approval` | bool | ❌ | Hold in `pending_approval` before writing FHIR (default: `true`) |

**Response `200 OK`**
```json
{
  "prescription": "PRESCRIPTION\n\n1. Paracetamol (Calpol / Crocin)\n   Form: Tablet | Strength: 500mg\n   Dose: 1 tablet | Route: Oral | Frequency: Three times daily\n   Duration: 5 days\n   Instructions: Take after food. Do not exceed 4g/day.\n\n2. ORS Sachets\n   Dose: 1 sachet dissolved in 1L water | As required for hydration",
  "follow_up": "FOLLOW-UP INSTRUCTIONS\n\n- Return immediately if you develop any of the following: bleeding gums, blood in urine/stool, severe abdominal pain, persistent vomiting, or breathlessness.\n- Drink at least 2–3 litres of oral fluids daily.\n- Avoid NSAIDs (e.g. Ibuprofen, Aspirin) — they increase bleeding risk.\n- Collect lab reports (CBC, Dengue NS1) and return in 24 hours or earlier if worsening.",
  "patient_summary": "PATIENT SUMMARY\n\nYou have been diagnosed with a suspected dengue-like illness. You have been given a medicine called Paracetamol to bring down your fever. Please drink plenty of fluids and rest. Come back to the hospital immediately if you notice any bleeding, severe tummy pain, or feel much worse.",
  "fhir_resources": "FHIR RESOURCES\n\n{\"resourceType\": \"MedicationRequest\", \"medicationCodeableConcept\": {\"text\": \"Paracetamol\"}, \"dosageInstruction\": [{\"text\": \"500mg oral — three times daily\"}]}",
  "status": "pending_approval",
  "user_id": "3d6f4f30-1b2c-4e5a-9f8d-7a1b2c3d4e5f"
}
```

---

#### `POST /prescription/{user_id}/approve`

Human-in-the-loop approval step. Finalises the prescription and writes FHIR MedicationRequest resources. Call `POST /generate` first.

**Request Body**
```json
{
  "patient_id": "patient-001",
  "override_prescription": null,
  "override_follow_up": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `patient_id` | string | ❌ | Required if not linked to session |
| `override_prescription` | string | ❌ | Replace the generated prescription text before finalising |
| `override_follow_up` | string | ❌ | Replace the follow-up instructions before finalising |

**Response `200 OK`**
```json
{
  "status": "finalized",
  "patient_id": "patient-001",
  "prescription": "PRESCRIPTION\n\n1. Paracetamol (Calpol / Crocin)\n   ...",
  "follow_up": "FOLLOW-UP INSTRUCTIONS\n\n- Return immediately if...",
  "patient_summary": "PATIENT SUMMARY\n\nYou have been diagnosed with...",
  "fhir_resources_written": 1,
  "fhir_results": [
    {
      "resourceType": "MedicationRequest",
      "id": "medreq-1a2b3c4d",
      "status": "active",
      "intent": "order",
      "medicationCodeableConcept": { "text": "Paracetamol" },
      "subject": { "reference": "Patient/patient-001" },
      "dosageInstruction": [{ "text": "500mg oral — three times daily" }]
    }
  ]
}
```

---

#### `GET /prescription/{user_id}/status`

Check whether a prescription has been generated and/or approved for a session.

**Response `200 OK` — pending approval**
```json
{
  "user_id": "3d6f4f30-1b2c-4e5a-9f8d-7a1b2c3d4e5f",
  "prescription_status": "pending_approval",
  "draft_available": true
}
```

**Response `200 OK` — not yet generated**
```json
{
  "user_id": "3d6f4f30-1b2c-4e5a-9f8d-7a1b2c3d4e5f",
  "prescription_status": "none",
  "draft_available": false
}
```

---

## Typical End-to-End Flow

```
1.  GET  /session-types                              # discover available types
2.  POST /patients                                   # register patient → get patient_id
3.  POST /sessions                                   # create session → get user_id
4.  POST /transcribe                                 # (optional) transcribe audio
5.  POST /sessions/{user_id}/message  ×N             # patient intake turns until complete=true
6.  POST /clinical/{user_id}/check-completeness      # extract clinical terms
7.  GET  /clinical/{user_id}/clarifying-question     # (if not complete) ask clarifying question
8.  POST /clinical/{user_id}/clarify  ×N             # submit answers until complete=true
9.  GET  /clinical/{user_id}/summary                 # generate clinical summary
10. POST /clinical/{user_id}/soap-note               # generate + persist SOAP note
11. POST /prescription/{user_id}/generate            # generate Rx (status=pending_approval)
12. GET  /prescription/{user_id}/status              # confirm draft is ready
13. POST /prescription/{user_id}/approve             # doctor approves → FHIR writes
14. POST /synthesize                                 # (optional) speak patient summary aloud
15. DELETE /sessions/{user_id}                       # end session
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | ✅ | GCP project ID |
| `GOOGLE_APPLICATION_CREDENTIALS` | ✅ | Path to GCP service account JSON key |
| `ADK_MODEL` | ❌ | Gemini model for all agents (default: `gemini-2.5-flash`) |
| `FHIR_DATASET` | ✅ | Cloud Healthcare dataset ID |
| `FHIR_STORE` | ✅ | FHIR store name within the dataset |
| `FHIR_LOCATION` | ✅ | GCP region for the Healthcare API e.g. `asia-south1` |

---

## Error Responses

All endpoints return standard HTTP error responses:

| Status | Meaning |
|---|---|
| `400` | Bad request — missing or empty body |
| `404` | Resource not found (session, patient, session type) |
| `409` | Conflict — e.g. session not yet complete when generating prescription |
| `422` | Validation error — invalid input |
| `502` | Upstream error — FHIR API or Google Cloud service failure |
| `500` | Internal agent error |

**Example `422`**
```json
{ "detail": "query must not be empty." }
```

**Example `404`**
```json
{ "detail": "Session not found or expired." }
```
