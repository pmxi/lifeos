"""Simplified Gmail tool wrappers for the LLM agent.

Wraps gmail.api functions with:
- Removed user_google_email param (single-user lifeos)
- Cleaned up function signatures for LLM tool calling
"""

from typing import Any, Literal

from lifeos.gmail.api import (
    draft_message as _draft_message,
    get_message as _get_message,
    get_thread as _get_thread,
    list_labels as _list_labels,
    modify_message_labels as _modify_message_labels,
    search_messages as _search_messages,
    send_message as _send_message,
)


async def search_gmail(
    query: str,
    page_size: int = 10,
    page_token: str | None = None,
) -> str:
    """Search Gmail messages."""
    return await _search_messages(query=query, page_size=page_size, page_token=page_token)


async def get_gmail_message(message_id: str) -> str:
    """Get full content of a Gmail message."""
    return await _get_message(message_id=message_id)


async def get_gmail_thread(thread_id: str) -> str:
    """Get all messages in a Gmail thread."""
    return await _get_thread(thread_id=thread_id)


async def send_gmail(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    body_format: Literal["plain", "html"] = "plain",
    thread_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """Send an email via Gmail."""
    return await _send_message(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        body_format=body_format,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        references=references,
    )


async def draft_gmail(
    subject: str,
    body: str,
    to: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    body_format: Literal["plain", "html"] = "plain",
    thread_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """Create a draft email in Gmail."""
    return await _draft_message(
        subject=subject,
        body=body,
        to=to,
        cc=cc,
        bcc=bcc,
        body_format=body_format,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        references=references,
    )


async def list_gmail_labels() -> str:
    """List all Gmail labels."""
    return await _list_labels()


async def modify_gmail_labels(
    message_id: str,
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> str:
    """Add or remove labels from a Gmail message."""
    return await _modify_message_labels(
        message_id=message_id,
        add_label_ids=add_label_ids,
        remove_label_ids=remove_label_ids,
    )


# Tool schemas for OpenAI function calling
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_gmail",
        "description": "Search Gmail messages using Gmail search syntax (e.g. 'from:user@example.com', 'subject:meeting', 'is:unread', 'newer_than:2d').",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query. Supports Gmail search operators.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Max messages to return (default 10).",
                },
                "page_token": {
                    "type": "string",
                    "description": "Pagination token from a previous search.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_gmail_message",
        "description": "Get the full content of a specific Gmail message by ID (subject, sender, body, attachments).",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID.",
                },
            },
            "required": ["message_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_gmail_thread",
        "description": "Get all messages in a Gmail conversation thread.",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Gmail thread ID.",
                },
            },
            "required": ["thread_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "send_gmail",
        "description": "Send an email via Gmail. Supports new emails and replies (provide thread_id + in_reply_to for replies).",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject.",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content.",
                },
                "cc": {
                    "type": "string",
                    "description": "CC email address.",
                },
                "bcc": {
                    "type": "string",
                    "description": "BCC email address.",
                },
                "body_format": {
                    "type": "string",
                    "enum": ["plain", "html"],
                    "description": "Body format: 'plain' (default) or 'html'.",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Gmail thread ID for replies.",
                },
                "in_reply_to": {
                    "type": "string",
                    "description": "Message-ID header of the message being replied to.",
                },
                "references": {
                    "type": "string",
                    "description": "Chain of Message-IDs for threading.",
                },
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "draft_gmail",
        "description": "Create a draft email in Gmail. Supports new drafts and reply drafts.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Email subject.",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content.",
                },
                "to": {
                    "type": "string",
                    "description": "Recipient email address (optional for drafts).",
                },
                "cc": {
                    "type": "string",
                    "description": "CC email address.",
                },
                "bcc": {
                    "type": "string",
                    "description": "BCC email address.",
                },
                "body_format": {
                    "type": "string",
                    "enum": ["plain", "html"],
                    "description": "Body format: 'plain' (default) or 'html'.",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Gmail thread ID for reply drafts.",
                },
                "in_reply_to": {
                    "type": "string",
                    "description": "Message-ID header of the message being replied to.",
                },
                "references": {
                    "type": "string",
                    "description": "Chain of Message-IDs for threading.",
                },
            },
            "required": ["subject", "body"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_gmail_labels",
        "description": "List all Gmail labels (system and user-created).",
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
        "name": "modify_gmail_labels",
        "description": "Add or remove labels from a Gmail message. Use to archive (remove INBOX), trash (add TRASH), mark read (remove UNREAD), etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID.",
                },
                "add_label_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label IDs to add (e.g. ['TRASH', 'STARRED']).",
                },
                "remove_label_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label IDs to remove (e.g. ['INBOX', 'UNREAD']).",
                },
            },
            "required": ["message_id"],
            "additionalProperties": False,
        },
    },
]
