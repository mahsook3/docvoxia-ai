"""
agents/clinical_assistant_agent.py
"""

from __future__ import annotations

import logging
import os
import json
import re
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Vertex AI – must be configured BEFORE any google.genai / ADK import
# that might instantiate a client.
# ---------------------------------------------------------------------------

def _configure_vertex_ai() -> None:
    """Assert required Vertex AI env vars and guarantee the ADK flag is set."""
    project = "docvoxia"
    if not project:
        raise EnvironmentError(
            "GOOGLE_CLOUD_PROJECT is not set. "
            "Add GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, and "
            "GOOGLE_GENAI_USE_VERTEXAI=true to your .env file."
        )
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")


_configure_vertex_ai()

# ---------------------------------------------------------------------------
# ADK / genai imports (after env vars are locked in)
# ---------------------------------------------------------------------------

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from tools.clinical_tools import (
    extract_medical_terms,
    check_drug_interactions,
    generate_soap_note,
)
from tools.fhir_tools import fhir_write_visit_note
from tools.translation_tools import translate_text
from utils.session_store import (
    get_session,
    update_session,
    append_history,
)


logger = logging.getLogger(__name__)

APP_NAME = "docvoxia"

_session_service = InMemorySessionService()


_SYSTEM_PROMPT = """
You are an AI Clinical Assistant supporting doctors.

Responsibilities:

- Analyse doctor patient conversations.
- Extract:
  symptoms,
  duration,
  severity,
  conditions,
  medications,
  observations,
  diagnoses,
  investigations.

- Detect possible drug interactions.

- Generate SOAP notes.

- Never invent medical information.

Return JSON:

{
 "conditions":[],
 "symptoms":[],
 "medications":[],
 "observations":[],
 "diagnoses":[],
 "investigations":[],
 "complete": false
}
"""


async def ensure_adk_session(user_id: str):
    try:
        existing = await _session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=user_id,
        )
        if existing:
            return existing
    except Exception:
        pass

    return await _session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=user_id,
    )


def build_clinical_assistant_agent() -> Agent:
    tools = [
        FunctionTool(extract_medical_terms),
        FunctionTool(check_drug_interactions),
        FunctionTool(generate_soap_note),
        FunctionTool(fhir_write_visit_note),
        FunctionTool(translate_text),
    ]

    return Agent(
        name="ClinicalAssistantAgent",
        model=os.getenv("ADK_MODEL", "gemini-2.5-flash"),
        description="Clinical extraction and SOAP generation agent",
        instruction=_SYSTEM_PROMPT,
        tools=tools,
    )


async def run_agent(agent: Agent, user_id: str, prompt: str) -> str:
    await ensure_adk_session(user_id)

    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=_session_service,
    )

    message = types.Content(
        role="user",
        parts=[types.Part(text=prompt)],
    )

    output = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=user_id,
        new_message=message,
    ):
        if event.content:
            for part in event.content.parts:
                if part.text:
                    output += part.text

    return output.strip()


async def check_completeness(
    agent: Agent,
    user_id: str,
    query: str,
) -> Dict[str, Any]:
    session = get_session(user_id)
    if not session:
        return {"error": "Session not found"}

    append_history(user_id, "user", query)

    prompt = f"""
Analyse this clinical query.

Session:
{session.get("session_type", {})}

Query:
{query}

Return JSON only.
"""

    try:
        raw = await run_agent(agent, user_id, prompt)
    except Exception as exc:
        logger.exception("Clinical agent error %s", exc)
        return {"complete": False, "error": str(exc)}

    parsed = _parse_json(raw)

    medical_terms = {
        "conditions":   parsed.get("conditions", []),
        "symptoms":     parsed.get("symptoms", []),
        "medications":  parsed.get("medications", []),
        "observations": parsed.get("observations", []),
        "diagnoses":    parsed.get("diagnoses", []),
    }

    complete = bool(parsed.get("complete", False))

    update_session(user_id, {"medical_terms": medical_terms, "complete": complete})
    append_history(user_id, "assistant", raw)

    return {"complete": complete, "medical_terms": medical_terms}


async def answer_clarification(agent, user_id, clarification):
    return await check_completeness(agent, user_id, clarification)


async def generate_clarifying_question(agent, user_id):
    session = get_session(user_id)
    if not session:
        return {"error": "Session missing"}

    prompt = f"""
Conversation:
{session.get("history", [])}

Find the single most important missing clinical question.
Return only question.
"""

    try:
        question = await run_agent(agent, user_id, prompt)
    except Exception:
        question = "Please describe your symptoms in more detail."

    return {"clarifying_question": question}


async def get_final_info(agent, user_id):
    session = get_session(user_id)
    if not session:
        return {"error": "Session missing"}

    conversation = "\n".join(
        f"{x['role']}: {x['content']}"
        for x in session.get("history", [])
    )

    prompt = f"""
Generate medical summary.

Conversation:
{conversation}

Include:
Chief complaint
History
Findings
Diagnosis
Plan
"""

    summary = await run_agent(agent, user_id, prompt)
    return {"formatted_info": summary}


def _parse_json(text: str) -> Dict[str, Any]:
    match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except Exception:
        return {}