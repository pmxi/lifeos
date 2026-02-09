import asyncio
import base64
import json
import logging
import os
from datetime import datetime
from typing import TypedDict, cast

from openai import AsyncOpenAI
from openai.types.responses import (
    ResponseInputContentParam,
    ResponseFunctionToolCall,
    ResponseInputItemParam,
    ResponseInputParam,
)

from lifeos.db import SCHEMA, execute_sql_tool
from lifeos.calendar_tools import (
    TOOLS as CALENDAR_TOOLS,
    create_event,
    delete_event,
    get_events,
    list_calendars,
    modify_event,
)
from lifeos.reminder_tools import (
    TOOLS as REMINDER_TOOLS,
    create_reminder,
    delete_reminder,
    list_reminders,
    update_reminder,
)

log = logging.getLogger(__name__)

# Conversation state: stores last response ID per chat for multi-turn context.
# Uses OpenAI's previous_response_id to chain responses (30-day TTL, stored on OpenAI).
# Future options (see https://platform.openai.com/docs/guides/conversation-state):
#   - Conversations API: persistent conversation objects, no TTL, managed by OpenAI
#   - Local storage: store messages in our DB for privacy-first, unlimited retention
_last_response_id: dict[str, str] = {}

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class UploadedFile(TypedDict):
    filename: str
    mime_type: str
    data: bytes

EXECUTE_SQL_TOOL = {
    "type": "function",
    "name": "execute_sql",
    "description": "Execute a SQL query against the SQLite database.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "SQLite query to execute"}
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}

TOOLS = [EXECUTE_SQL_TOOL] + CALENDAR_TOOLS + REMINDER_TOOLS

INSTRUCTIONS = f"""You are a personal assistant with direct database access and Google Calendar integration.

Database schema:
{SCHEMA}

Current time: {{timestamp}}

Default to timezone America/Indiana/Indianapolis.

User is Paras Mittal, a computer science undergrad student at Purdue in West Lafayette.

Tools:
- execute_sql: Read/write tasks and notes in the database
- list_calendars: List available calendars
- get_events, create_event, modify_event, delete_event: Manage calendar events
  Default to calendar_id="primary" unless the user specifies a different calendar.
- create_reminder, list_reminders, update_reminder, delete_reminder: Manage reminders
  Reminders wake you up at a scheduled time to run a prompt and send the response.
  Use proactively when user asks to be reminded of something.

Be direct. No pleasantries.
"""


def get_instructions() -> str:
    return INSTRUCTIONS.format(timestamp=datetime.now().isoformat())


def clear_conversation(chat_id: str) -> None:
    """Clear conversation history for a chat."""
    _last_response_id.pop(chat_id, None)

# the connection between using previous_response_id
# and input parameter doesn't seem precisely documented.

async def process_message(
    user_message: str,
    chat_id: str,
    image_data: bytes | None = None,
    uploaded_file: UploadedFile | None = None,
) -> str:
    log.debug("Processing message: %s", user_message)

    # Build content array for multimodal input
    input_items: ResponseInputParam
    if image_data or uploaded_file:
        content: list[ResponseInputContentParam] = []
        if user_message:
            content.append(
                cast(ResponseInputContentParam, {"type": "input_text", "text": user_message})
            )

        if image_data:
            b64_image = base64.b64encode(image_data).decode("utf-8")
            content.append(
                cast(
                    ResponseInputContentParam,
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{b64_image}",
                        "detail": "auto",
                    },
                )
            )

        if uploaded_file:
            b64_file = base64.b64encode(uploaded_file["data"]).decode("utf-8")
            content.append(
                cast(
                    ResponseInputContentParam,
                    {
                        "type": "input_file",
                        "filename": uploaded_file["filename"],
                        "file_data": f"data:{uploaded_file['mime_type']};base64,{b64_file}",
                    },
                )
            )

        input_items = cast(ResponseInputParam, [{"role": "user", "content": content}])
    else:
        input_items = cast(ResponseInputParam, [{"role": "user", "content": user_message}])

    while True:
        log.debug("Calling OpenAI API")
        response = await client.responses.create(
            model="gpt-5.2",
            instructions=get_instructions(),
            input=input_items,
            tools=TOOLS,  # type: ignore TODO fix this typing.
            previous_response_id=_last_response_id.get(chat_id),
            store=True,
        )
        _last_response_id[chat_id] = response.id
        log.debug("OpenAI Response Object: %s", response.model_dump_json(indent=2))

        # Check for function calls in output
        function_calls = [
            cast(ResponseFunctionToolCall, item)
            for item in response.output
            if item.type == "function_call"
        ]

        if function_calls:
            # Only pass tool outputs; previous_response_id carries the function_call context
            tool_outputs: list[ResponseInputItemParam] = []
            for fc in function_calls:
                try:
                    args = json.loads(fc.arguments) if fc.arguments else {}
                except json.JSONDecodeError as exc:
                    log.exception("Invalid arguments for tool %s", fc.name)
                    tool_outputs.append(
                        cast(
                            ResponseInputItemParam,
                            {
                                "type": "function_call_output",
                                "call_id": fc.call_id,
                                "output": f"Invalid arguments for {fc.name}: {exc}",
                            },
                        )
                    )
                    continue

                try:
                    if fc.name == "execute_sql":
                        log.info("Executing SQL: %s", args.get("query"))
                        result = await asyncio.to_thread(
                            execute_sql_tool, args["query"]
                        )
                        log.debug("SQL result: %s", result)
                        output = json.dumps(result)
                    elif fc.name == "list_calendars":
                        output = await list_calendars(**args)
                    elif fc.name == "get_events":
                        output = await get_events(**args)
                    elif fc.name == "create_event":
                        output = await create_event(**args)
                    elif fc.name == "modify_event":
                        output = await modify_event(**args)
                    elif fc.name == "delete_event":
                        output = await delete_event(**args)
                    elif fc.name == "create_reminder":
                        output = await asyncio.to_thread(create_reminder, **args)
                    elif fc.name == "list_reminders":
                        output = await asyncio.to_thread(list_reminders)
                    elif fc.name == "update_reminder":
                        output = await asyncio.to_thread(update_reminder, **args)
                    elif fc.name == "delete_reminder":
                        output = await asyncio.to_thread(delete_reminder, **args)
                    else:
                        output = f"Unknown tool: {fc.name}"
                except Exception as exc:
                    log.exception("Tool error in %s", fc.name)
                    output = f"Tool error in {fc.name}: {exc}"

                tool_outputs.append(
                    cast(
                        ResponseInputItemParam,
                        {
                            "type": "function_call_output",
                            "call_id": fc.call_id,
                            "output": output,
                        },
                    )
                )
            input_items = tool_outputs
        else:
            # I'm worried this will swallow errors
            return response.output_text or ""
