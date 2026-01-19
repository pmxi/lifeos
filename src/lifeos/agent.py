import asyncio
import json
import logging
import os
from datetime import datetime

from openai import AsyncOpenAI

from lifeos.db import SCHEMA, execute_sql_tool
from lifeos.calendar_tools import (
    TOOLS as CALENDAR_TOOLS,
    create_event,
    delete_event,
    get_events,
    list_calendars,
    modify_event,
)

log = logging.getLogger(__name__)

# Conversation state: stores last response ID per chat for multi-turn context.
# Uses OpenAI's previous_response_id to chain responses (30-day TTL, stored on OpenAI).
# Future options (see https://platform.openai.com/docs/guides/conversation-state):
#   - Conversations API: persistent conversation objects, no TTL, managed by OpenAI
#   - Local storage: store messages in our DB for privacy-first, unlimited retention
_last_response_id: dict[str, str] = {}

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

TOOLS = [EXECUTE_SQL_TOOL] + CALENDAR_TOOLS

INSTRUCTIONS = f"""You are a personal assistant with direct database access. You manage tasks and notes.

Database schema:
{SCHEMA}

Current time: {{timestamp}}

Use execute_sql to read/write data. Be direct. No pleasantries.
"""


def get_instructions() -> str:
    return INSTRUCTIONS.format(timestamp=datetime.now().isoformat())

# the connection between using previous_response_id
# and input parameter doesn't seem precisely documented.

async def process_message(user_message: str, chat_id: str) -> str:
    log.debug("Processing message: %s", user_message)
    input_items: list = [{"role": "user", "content": user_message}]

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
        function_calls = [item for item in response.output if item.type == "function_call"]

        if function_calls:
            # Only pass tool outputs; previous_response_id carries the function_call context
            input_items = []
            for fc in function_calls:
                try:
                    args = json.loads(fc.arguments) if fc.arguments else {}
                except json.JSONDecodeError as exc:
                    log.exception("Invalid arguments for tool %s", fc.name)
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": fc.call_id,
                            "output": f"Invalid arguments for {fc.name}: {exc}",
                        }
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
                    else:
                        output = f"Unknown tool: {fc.name}"
                except Exception as exc:
                    log.exception("Tool error in %s", fc.name)
                    output = f"Tool error in {fc.name}: {exc}"

                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": output,
                    }
                )
        else:
            # I'm worried this will swallow errors
            return response.output_text or ""
