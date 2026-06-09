"""
agents/prescription_agent.py
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types


from tools.prescription_tools import (
    generate_prescription,
    create_medication_request,
    create_care_plan,
)

from tools.translation_tools import translate_text
from tools.speech_tools import synthesize_speech


from utils.session_store import get_session


logger = logging.getLogger(__name__)


APP_NAME = "docvoxia"


_session_service = InMemorySessionService()



_SYSTEM_PROMPT = """
You are a Prescription and Care Planning Assistant.

Responsibilities:

1. Generate structured prescriptions.

Include:

- generic name
- brand name
- strength
- dosage form
- dose
- route
- frequency
- duration
- instructions


2. Generate:

- follow-up instructions
- emergency guidance
- lifestyle advice
- adherence tips


3. Create FHIR MedicationRequest resources.

4. Flag:

- allergy conflicts
- high-risk medications


Rules:

Never invent medications or doses.

Use only provided clinical information.


Format:

[PRESCRIPTION]

[FOLLOW-UP INSTRUCTIONS]

[PATIENT SUMMARY]

[FHIR RESOURCES]
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






def build_prescription_agent()->Agent:


    tools=[

        FunctionTool(
            generate_prescription
        ),

        FunctionTool(
            create_medication_request
        ),

        FunctionTool(
            create_care_plan
        ),

        FunctionTool(
            translate_text
        ),

        FunctionTool(
            synthesize_speech
        ),

    ]



    return Agent(

        name="PrescriptionAgent",

        model=os.getenv(
            "ADK_MODEL",
            "gemini-2.5-flash"
        ),

        description=(
            "Creates prescriptions and FHIR medication resources"
        ),

        instruction=_SYSTEM_PROMPT,

        tools=tools,

    )







async def run_agent(
    agent:Agent,
    user_id:str,
    prompt:str
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







async def generate_session_prescription(

    agent:Agent,

    user_id:str,

    target_language:str="en",

    require_approval:bool=True,

)->Dict[str,Any]:


    session = get_session(
        user_id
    )


    if not session:

        return {
            "error":
            "Session not found"
        }



    if not session.get(
        "complete"
    ):

        return {
            "error":
            "Session incomplete"
        }




    medical_terms = session.get(
        "medical_terms",
        {}
    )


    history = session.get(
        "history",
        []
    )


    session_type = session.get(
        "session_type",
        {}
    )


    patient_id = session.get(
        "patient_id"
    )



    transcript = "\n".join(

        f"{h['role'].upper()}: {h['content']}"

        for h in history

    )



    prompt=f"""

Generate prescription.

Session:

{session_type.get("name")}


Patient FHIR ID:

{patient_id}


Target language:

{target_language}



Clinical information:

{medical_terms}



Consultation:

{transcript}


Generate:

Prescription

Follow-up

Patient summary

FHIR MedicationRequest


"""



    try:

        output = await run_agent(

            agent,

            user_id,

            prompt

        )


    except Exception as exc:

        logger.exception(
            "PrescriptionAgent error %s",
            exc
        )

        return {
            "error":
            str(exc)
        }





    sections=_parse_sections(
        output
    )



    return {

        "prescription":
            sections.get(
                "PRESCRIPTION",
                ""
            ),

        "follow_up":
            sections.get(
                "FOLLOW-UP INSTRUCTIONS",
                ""
            ),

        "patient_summary":
            sections.get(
                "PATIENT SUMMARY",
                ""
            ),

        "fhir_resources":
            sections.get(
                "FHIR RESOURCES",
                ""
            ),

        "status":
            (
                "pending_approval"
                if require_approval
                else
                "finalized"
            ),

        "user_id":
            user_id,

    }








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

        content=adk_result.content


        if isinstance(
            content,
            list
        ):

            return " ".join(

                x.get(
                    "text",
                    ""
                )

                if isinstance(
                    x,
                    dict
                )

                else str(x)

                for x in content

            )


        return str(content)


    return str(adk_result)







def _parse_sections(
    text:str
)->Dict[str,str]:

    import re


    parts = re.split(
        r"\[([A-Z /\-]+)\]",
        text
    )


    result={}


    i=1


    while i+1 < len(parts):

        key=parts[i].strip()

        value=parts[i+1].strip()

        result[key]=value

        i += 2


    return result