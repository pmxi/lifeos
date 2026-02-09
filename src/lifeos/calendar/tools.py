"""Simplified calendar tool wrappers for the LLM agent.

Wraps calendar.api functions with:
- Removed unused parameters (color, meet, transparency, visibility, attachments)
- Default reminders (no custom reminder support)
- detailed=True by default for get_events
"""

from typing import Any

from lifeos.calendar.api import (
    create_event as _create_event,
    delete_event as _delete_event,
    get_events as _get_events,
    list_calendars as _list_calendars,
    modify_event as _modify_event,
)


async def list_calendars() -> str:
    """List all accessible calendars."""
    return await _list_calendars()


async def get_events(
    calendar_id: str = "primary",
    event_id: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 25,
    query: str | None = None,
) -> str:
    """Get calendar events, optionally filtered by time range or search query."""
    return await _get_events(
        calendar_id=calendar_id,
        event_id=event_id,
        time_min=time_min,
        time_max=time_max,
        max_results=max_results,
        query=query,
        detailed=True,
    )


async def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    timezone: str | None = None,
) -> str:
    """Create a new calendar event."""
    return await _create_event(
        calendar_id=calendar_id,
        summary=summary,
        start_time=start_time,
        end_time=end_time,
        description=description,
        location=location,
        attendees=attendees,
        timezone=timezone,
    )


async def modify_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    timezone: str | None = None,
) -> str:
    """Modify an existing calendar event. Only provided fields are updated."""
    return await _modify_event(
        calendar_id=calendar_id,
        event_id=event_id,
        summary=summary,
        start_time=start_time,
        end_time=end_time,
        description=description,
        location=location,
        attendees=attendees,
        timezone=timezone,
    )


async def delete_event(event_id: str, calendar_id: str = "primary") -> str:
    """Delete a calendar event by ID."""
    return await _delete_event(
        calendar_id=calendar_id,
        event_id=event_id,
    )


# Tool schemas for OpenAI function calling
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "list_calendars",
        "description": "List all calendars accessible to the user.",
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
        "name": "get_events",
        "description": "Get calendar events. Returns upcoming events by default, or filter by time range/search.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to query. Use 'primary' for main calendar.",
                },
                "event_id": {
                    "type": "string",
                    "description": "Specific event ID to fetch. If set, ignores time filters.",
                },
                "time_min": {
                    "type": "string",
                    "description": "Start of time range (RFC3339 or YYYY-MM-DD). Defaults to now.",
                },
                "time_max": {
                    "type": "string",
                    "description": "End of time range (RFC3339 or YYYY-MM-DD).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum events to return (default 25, max 250).",
                },
                "query": {
                    "type": "string",
                    "description": "Search query for event title, description, or location.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "create_event",
        "description": "Create a new calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Event title.",
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time (RFC3339 e.g. 2024-01-15T10:00:00Z, or YYYY-MM-DD for all-day).",
                },
                "end_time": {
                    "type": "string",
                    "description": "End time (RFC3339 or YYYY-MM-DD for all-day).",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Use 'primary' for main calendar.",
                },
                "description": {
                    "type": "string",
                    "description": "Event description.",
                },
                "location": {
                    "type": "string",
                    "description": "Event location.",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses.",
                },
                "timezone": {
                    "type": "string",
                    "description": "Timezone (e.g. America/New_York). Defaults to calendar timezone.",
                },
            },
            "required": ["summary", "start_time", "end_time"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "modify_event",
        "description": "Modify an existing calendar event. Only provided fields are updated.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID of the event to modify.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Use 'primary' for main calendar.",
                },
                "summary": {
                    "type": "string",
                    "description": "New event title.",
                },
                "start_time": {
                    "type": "string",
                    "description": "New start time (RFC3339 or YYYY-MM-DD).",
                },
                "end_time": {
                    "type": "string",
                    "description": "New end time (RFC3339 or YYYY-MM-DD).",
                },
                "description": {
                    "type": "string",
                    "description": "New event description.",
                },
                "location": {
                    "type": "string",
                    "description": "New event location.",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New list of attendee email addresses (replaces existing).",
                },
                "timezone": {
                    "type": "string",
                    "description": "New timezone for start/end times.",
                },
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "delete_event",
        "description": "Delete a calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID of the event to delete.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Use 'primary' for main calendar.",
                },
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
    },
]
