"""
agents/patient_care_agent.py
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from google.adk.tools import FunctionTool

from tools.translation_tools import translate_text
from tools.fhir_tools import (
    register_patient,
    lookup_patient,
    book_appointment,
)

from tools.speech_tools import synthesize_speech

from utils.session_store import (
    get_session,
    update_session,
    append_history,
)


logger = logging.getLogger(__name__)


APP_NAME = "docvoxia"


_SYSTEM_PROMPT = """
You are a compassionate multilingual Patient Care Assistant.

Responsibilities:

1. Collect:
- patient name
- age
- gender
- phone/contact
- chief complaint

2. Help with:
- registration
- patient lookup
- appointment booking

3. Use translation tools when needed.

4. Never diagnose.

5. Keep responses short and reassuring.

When intake is finished output exactly:

INTAKE_COMPLETE
"""


# ADK memory
_session_service = InMemorySessionService()


async def ensure_adk_session(user_id: str):

    try:
        session = await _session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=user_id,
        )

        if session:
            return session

    except Exception:
        pass


    return await _session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=user_id,
    )



def build_patient_care_agent() -> Agent:

    tools = [
        FunctionTool(translate_text),
        FunctionTool(register_patient),
        FunctionTool(lookup_patient),
        FunctionTool(book_appointment),
        FunctionTool(synthesize_speech),
    ]


    agent = Agent(
        name="PatientCareAgent",
        model=os.getenv(
            "ADK_MODEL",
            "gemini-2.5-flash",
        ),
        description=(
            "Patient intake and FHIR registration agent"
        ),
        instruction=_SYSTEM_PROMPT,
        tools=tools,
    )

    return agent



async def run_intake_turn(
    agent: Agent,
    user_id: str,
    user_message: str,
) -> Dict[str, Any]:


    session = get_session(user_id)


    if not session:
        return {
            "error": "Session not found",
            "complete": False,
        }


    append_history(
        user_id,
        "user",
        user_message,
    )


    history = session.get(
        "history",
        []
    )


    session_type = session.get(
        "session_type",
        {}
    )


    prompt = f"""
SESSION TYPE:
{session_type.get("name","General")}

REQUIRED FIELDS:
{session_type.get("required_fields",[])}


Conversation:

"""


    for item in history[-10:]:

        prompt += (
            f"{item['role']}: "
            f"{item['content']}\n"
        )


    prompt += (
        "\nPatient:\n"
        + user_message
    )


    try:

        await ensure_adk_session(user_id)


        runner = Runner(
            agent=agent,
            app_name=APP_NAME,
            session_service=_session_service,
        )


        content = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=prompt
                )
            ],
        )


        reply_text = ""


        async for event in runner.run_async(
            user_id=user_id,
            session_id=user_id,
            new_message=content,
        ):

            if event.content:

                for part in event.content.parts:

                    if part.text:
                        reply_text += part.text


        reply_text = reply_text.strip()


    except Exception as exc:

        logger.exception(
            "PatientCareAgent error: %s",
            exc,
        )

        reply_text = (
            "Sorry, I could not process that. "
            "Please try again."
        )



    complete = (
        "INTAKE_COMPLETE"
        in reply_text
    )


    clean_reply = (
        reply_text
        .replace(
            "INTAKE_COMPLETE",
            "",
        )
        .strip()
    )


    append_history(
        user_id,
        "assistant",
        clean_reply,
    )


    update_session(
        user_id,
        {
            "complete": complete
        },
    )


    return {
        "reply": clean_reply,
        "complete": complete,
        "session": get_session(user_id),
    }