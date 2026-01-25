"""Reminder tools for scheduling agent wake-ups.

Allows the agent to create/manage reminders that trigger at scheduled times,
running a prompt through the agent and sending the response to the user.
"""

import json
from typing import Any

from lifeos.db import execute_sql_tool


def create_reminder(prompt: str, trigger_at: str) -> str:
    """Create a new reminder.

    Args:
        prompt: The prompt to run when the reminder triggers.
        trigger_at: When to trigger (RFC 3339 datetime).

    Returns:
        JSON string with the created reminder ID.
    """
    result = execute_sql_tool(
        f"INSERT INTO reminder (prompt, trigger_at) VALUES ('{prompt.replace(chr(39), chr(39)+chr(39))}', '{trigger_at}') RETURNING id"
    )
    return json.dumps(result)


def list_reminders() -> str:
    """List all pending reminders.

    Returns:
        JSON string with list of pending reminders.
    """
    result = execute_sql_tool(
        "SELECT id, prompt, trigger_at, status, created_at FROM reminder WHERE status = 'pending' ORDER BY trigger_at"
    )
    return json.dumps(result)


def update_reminder(
    id: int, prompt: str | None = None, trigger_at: str | None = None
) -> str:
    """Update an existing reminder.

    Args:
        id: Reminder ID to update.
        prompt: New prompt text (optional).
        trigger_at: New trigger time (optional).

    Returns:
        JSON string with rows affected.
    """
    updates = []
    if prompt is not None:
        updates.append(f"prompt = '{prompt.replace(chr(39), chr(39)+chr(39))}'")
    if trigger_at is not None:
        updates.append(f"trigger_at = '{trigger_at}'")

    if not updates:
        return json.dumps({"error": "No fields to update"})

    result = execute_sql_tool(
        f"UPDATE reminder SET {', '.join(updates)} WHERE id = {id} AND status = 'pending'"
    )
    return json.dumps(result)


def delete_reminder(id: int) -> str:
    """Delete (cancel) a reminder.

    Args:
        id: Reminder ID to delete.

    Returns:
        JSON string with rows affected.
    """
    result = execute_sql_tool(
        f"UPDATE reminder SET status = 'cancelled' WHERE id = {id} AND status = 'pending'"
    )
    return json.dumps(result)


# Tool schemas for OpenAI function calling
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "create_reminder",
        "description": "Create a reminder that will wake up the assistant at a scheduled time to run a prompt and send the response. Use this proactively when the user asks to be reminded of something.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt to run when the reminder triggers. Should include context about what to remind the user about.",
                },
                "trigger_at": {
                    "type": "string",
                    "description": "When to trigger the reminder (RFC 3339 datetime, e.g. 2024-01-15T10:00:00-05:00).",
                },
            },
            "required": ["prompt", "trigger_at"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_reminders",
        "description": "List all pending reminders.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "update_reminder",
        "description": "Update an existing pending reminder's prompt or trigger time.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "ID of the reminder to update.",
                },
                "prompt": {
                    "type": "string",
                    "description": "New prompt text.",
                },
                "trigger_at": {
                    "type": "string",
                    "description": "New trigger time (RFC 3339 datetime).",
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "delete_reminder",
        "description": "Cancel/delete a pending reminder.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "ID of the reminder to delete.",
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]
