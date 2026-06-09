"""
agents/healthcare_data_agent.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types


from tools.fhir_tools import (
    register_patient,
    lookup_patient,
    book_appointment,

    fhir_write_visit_note,
    fhir_create_condition,
    fhir_create_medication_request,
    fhir_create_observation,
    fhir_get_patient_context,
)


logger = logging.getLogger(__name__)


APP_NAME = "docvoxia"


_session_service = InMemorySessionService()



_SYSTEM_PROMPT = """
You are Healthcare Data Agent.

Responsibilities:

- Manage all FHIR operations.
- Create and update resources.
- Validate required fields.
- Maintain healthcare data quality.

Resources:

Patient
Condition
MedicationRequest
Observation
DocumentReference
CarePlan
Appointment


Rules:

1. Validate input before writing.
2. Never create invalid FHIR resources.
3. Return clear errors.
4. Use tools for all FHIR operations.
5. Return structured confirmations.
"""




async def ensure_adk_session(
    user_id:str
):

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





def build_healthcare_data_agent()->Agent:


    tools=[

        FunctionTool(
            register_patient
        ),

        FunctionTool(
            lookup_patient
        ),

        FunctionTool(
            book_appointment
        ),

        FunctionTool(
            fhir_write_visit_note
        ),

        FunctionTool(
            fhir_create_condition
        ),

        FunctionTool(
            fhir_create_medication_request
        ),

        FunctionTool(
            fhir_create_observation
        ),

        FunctionTool(
            fhir_get_patient_context
        ),

    ]



    return Agent(

        name="HealthcareDataAgent",

        model=os.getenv(
            "ADK_MODEL",
            "gemini-2.5-flash"
        ),

        description=(
            "FHIR data management agent "
            "using Google Healthcare API"
        ),

        instruction=_SYSTEM_PROMPT,

        tools=tools,

    )






async def run_agent(
    agent:Agent,
    user_id:str,
    prompt:str,
)->str:


    await ensure_adk_session(
        user_id
    )


    runner = Runner(

        agent=agent,

        app_name=APP_NAME,

        session_service=_session_service,

    )



    message = types.Content(

        role="user",

        parts=[

            types.Part(
                text=prompt
            )

        ],

    )



    output=""


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







async def get_patient_context(

    agent:Agent,

    patient_id:str,

)->str:


    prompt=f"""

Fetch complete patient context.

Patient ID:

{patient_id}


Include:

- demographics
- conditions
- medications
- allergies
- observations
- appointments


Use fhir_get_patient_context tool.

"""


    try:


        result = await run_agent(

            agent,

            patient_id,

            prompt,

        )


        return result



    except Exception as exc:


        logger.exception(

            "HealthcareDataAgent error: %s",

            exc,

        )


        return (
            f"[FHIR context error: {exc}]"
        )





def _extract_text(
    adk_result:Any
)->str:


    if isinstance(
        adk_result,
        str
    ):

        return adk_result



    if hasattr(
        adk_result,
        "text"
    ):

        return adk_result.text or ""



    if hasattr(
        adk_result,
        "content"
    ):


        content = adk_result.content


        if isinstance(
            content,
            list
        ):

            return " ".join(

                x.get("text","")

                if isinstance(x,dict)

                else str(x)

                for x in content

            )


        return str(content)



    return str(adk_result)