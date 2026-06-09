"""
main.py
-------
Healthcare AI Backend — Google ADK Multi-Agent System

Agents:
  - PatientCareAgent      : multilingual intake, registration, appointment flows
  - ClinicalAssistantAgent: doctor support, symptom/diagnosis/med extraction
  - PrescriptionAgent     : post-consult prescriptions, follow-ups, records
  - HealthcareDataAgent   : FHIR data exchange (Google Cloud Healthcare API)

Infrastructure:
  - Google Cloud Speech-to-Text v2 (Chirp 3) for ASR
  - Google Cloud TTS for voice output
  - Google Cloud Translation for multilingual support
  - Google Cloud Healthcare FHIR for records
  - Google ADK for agent orchestration + tool calling
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers import asr, tts, patients, sessions, clinical, prescription

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Healthcare ADK backend starting up...")
    logger.info("   Agents: PatientCare | ClinicalAssistant | Prescription | HealthcareData")
    yield
    logger.info("🛑 Shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Healthcare AI — Multi-Agent Backend",
    description=(
        "Google ADK-powered multi-agent system for patient care, clinical assistance, "
        "prescription management, and FHIR-based healthcare data exchange."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(asr.router,          prefix="",        tags=["ASR"])
app.include_router(tts.router,          prefix="",        tags=["TTS"])
app.include_router(patients.router,     prefix="",        tags=["Patients / FHIR"])
app.include_router(sessions.router,     prefix="",        tags=["Sessions"])
app.include_router(clinical.router,     prefix="",        tags=["Clinical Assistant"])
app.include_router(prescription.router, prefix="",        tags=["Prescription"])


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {
        "status":  "ok",
        "version": "2.0.0",
        "agents":  [
            "PatientCareAgent",
            "ClinicalAssistantAgent",
            "PrescriptionAgent",
            "HealthcareDataAgent",
        ],
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "service": "Healthcare AI Backend",
        "docs":    "/docs",
        "health":  "/health",
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)