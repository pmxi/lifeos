import asyncio
import json
import logging
import os
from datetime import datetime

from openai import AsyncOpenAI

from lifeos.db import SCHEMA, execute_sql_tool
from lifeos.google_calendar import (
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

TOOLS = [
    {
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
    },
    {
        "type": "function",
        "name": "list_calendars",
        "description": "List calendars accessible to the authenticated Google account.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_google_email": {
                    "type": "string",
                    "description": "Optional label for the account (defaults to GOOGLE_USER_EMAIL).",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_events",
        "description": "Retrieve events from a Google Calendar, optionally filtered by time range.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_google_email": {
                    "type": "string",
                    "description": "Optional label for the account (defaults to GOOGLE_USER_EMAIL).",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (default: primary).",
                },
                "event_id": {
                    "type": "string",
                    "description": "Specific event ID to fetch. If set, ignores time filters.",
                },
                "time_min": {
                    "type": "string",
                    "description": "RFC3339 start time (inclusive), or YYYY-MM-DD for all-day.",
                },
                "time_max": {
                    "type": "string",
                    "description": "RFC3339 end time (exclusive).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of events to return (default: 25).",
                    "minimum": 1,
                    "maximum": 250,
                },
                "query": {
                    "type": "string",
                    "description": "Keyword query over summary/description/location.",
                },
                "detailed": {
                    "type": "boolean",
                    "description": "Return detailed event info when true.",
                },
                "include_attachments": {
                    "type": "boolean",
                    "description": "Include attachment details when detailed=true.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_event",
        "description": "Create a Google Calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_google_email": {
                    "type": "string",
                    "description": "Optional label for the account (defaults to GOOGLE_USER_EMAIL).",
                },
                "summary": {"type": "string", "description": "Event title."},
                "start_time": {
                    "type": "string",
                    "description": "RFC3339 start time or YYYY-MM-DD for all-day.",
                },
                "end_time": {
                    "type": "string",
                    "description": "RFC3339 end time or YYYY-MM-DD for all-day.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (default: primary).",
                },
                "description": {"type": "string", "description": "Event description."},
                "location": {"type": "string", "description": "Event location."},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses.",
                },
                "timezone": {
                    "type": "string",
                    "description": "Timezone ID, e.g. America/New_York.",
                },
                "attachments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Drive file URLs or IDs to attach.",
                },
                "add_google_meet": {
                    "type": "boolean",
                    "description": "Add a Google Meet conference to the event.",
                },
                "reminders": {
                    "type": "array",
                    "description": "Custom reminders (max 5).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "method": {
                                "type": "string",
                                "enum": ["popup", "email"],
                            },
                            "minutes": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 40320,
                            },
                        },
                        "required": ["method", "minutes"],
                        "additionalProperties": False,
                    },
                },
                "use_default_reminders": {
                    "type": "boolean",
                    "description": "Use the calendar's default reminders.",
                },
                "transparency": {
                    "type": "string",
                    "enum": ["opaque", "transparent"],
                    "description": "Busy/free status.",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["default", "public", "private", "confidential"],
                    "description": "Event visibility.",
                },
            },
            "required": ["summary", "start_time", "end_time"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "modify_event",
        "description": "Modify an existing Google Calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_google_email": {
                    "type": "string",
                    "description": "Optional label for the account (defaults to GOOGLE_USER_EMAIL).",
                },
                "event_id": {"type": "string", "description": "Event ID to modify."},
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (default: primary).",
                },
                "summary": {"type": "string", "description": "New event title."},
                "start_time": {
                    "type": "string",
                    "description": "New RFC3339 start time or YYYY-MM-DD for all-day.",
                },
                "end_time": {
                    "type": "string",
                    "description": "New RFC3339 end time or YYYY-MM-DD for all-day.",
                },
                "description": {"type": "string", "description": "New description."},
                "location": {"type": "string", "description": "New location."},
                "attendees": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "email": {"type": "string"},
                                    "responseStatus": {"type": "string"},
                                    "organizer": {"type": "boolean"},
                                    "optional": {"type": "boolean"},
                                },
                                "required": ["email"],
                                "additionalProperties": False,
                            },
                        },
                    ],
                    "description": "Attendees as emails or attendee objects.",
                },
                "timezone": {
                    "type": "string",
                    "description": "Timezone ID, e.g. America/New_York.",
                },
                "add_google_meet": {
                    "type": "boolean",
                    "description": "True to add Meet, false to remove it.",
                },
                "reminders": {
                    "type": "array",
                    "description": "Replace reminders (max 5).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "method": {
                                "type": "string",
                                "enum": ["popup", "email"],
                            },
                            "minutes": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 40320,
                            },
                        },
                        "required": ["method", "minutes"],
                        "additionalProperties": False,
                    },
                },
                "use_default_reminders": {
                    "type": "boolean",
                    "description": "Use calendar defaults for reminders.",
                },
                "transparency": {
                    "type": "string",
                    "enum": ["opaque", "transparent"],
                    "description": "Busy/free status.",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["default", "public", "private", "confidential"],
                    "description": "Event visibility.",
                },
                "color_id": {
                    "type": "string",
                    "description": "Event color ID (1-11).",
                },
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "delete_event",
        "description": "Delete a Google Calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_google_email": {
                    "type": "string",
                    "description": "Optional label for the account (defaults to GOOGLE_USER_EMAIL).",
                },
                "event_id": {"type": "string", "description": "Event ID to delete."},
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (default: primary).",
                },
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

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
