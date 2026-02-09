import asyncio
import base64
import logging
from email.mime.text import MIMEText
from html.parser import HTMLParser
from typing import Any, Literal

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from lifeos.google_auth import DEFAULT_GMAIL_SCOPES, get_credentials

logger = logging.getLogger(__name__)

_gmail_service = None
_gmail_service_lock = asyncio.Lock()

HTML_BODY_TRUNCATE_LIMIT = 20000
GMAIL_METADATA_HEADERS = ["Subject", "From", "To", "Cc", "Message-ID", "Date"]


class _HTMLTextExtractor(HTMLParser):
    """Extract readable text from HTML using stdlib."""

    def __init__(self) -> None:
        super().__init__()
        self._text: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._skip = tag in ("script", "style")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._text.append(data)

    def get_text(self) -> str:
        return " ".join("".join(self._text).split())


def _html_to_text(html: str) -> str:
    """Convert HTML to readable plain text."""
    try:
        parser = _HTMLTextExtractor()
        parser.feed(html)
        return parser.get_text()
    except Exception:
        return html


def _extract_message_bodies(payload: dict[str, Any]) -> dict[str, str]:
    """Extract both plain text and HTML bodies from a Gmail message payload."""
    text_body = ""
    html_body = ""
    parts = [payload] if "parts" not in payload else payload.get("parts", [])

    part_queue = list(parts)
    while part_queue:
        part = part_queue.pop(0)
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")

        if body_data:
            try:
                decoded_data = base64.urlsafe_b64decode(body_data).decode(
                    "utf-8", errors="ignore"
                )
                if mime_type == "text/plain" and not text_body:
                    text_body = decoded_data
                elif mime_type == "text/html" and not html_body:
                    html_body = decoded_data
            except Exception as e:
                logger.warning("Failed to decode body part: %s", e)

        if mime_type.startswith("multipart/") and "parts" in part:
            part_queue.extend(part.get("parts", []))

    # Check the main payload if it has body data directly
    if payload.get("body", {}).get("data"):
        try:
            decoded_data = base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="ignore"
            )
            mime_type = payload.get("mimeType", "")
            if mime_type == "text/plain" and not text_body:
                text_body = decoded_data
            elif mime_type == "text/html" and not html_body:
                html_body = decoded_data
        except Exception as e:
            logger.warning("Failed to decode main payload body: %s", e)

    return {"text": text_body, "html": html_body}


def _format_body_content(text_body: str, html_body: str) -> str:
    """Format message body content with HTML fallback and truncation."""
    text_stripped = text_body.strip()
    html_stripped = html_body.strip()

    use_html = html_stripped and (
        not text_stripped
        or "<!--" in text_stripped
        or len(html_stripped) > len(text_stripped) * 50
    )

    if use_html:
        content = _html_to_text(html_stripped)
        if len(content) > HTML_BODY_TRUNCATE_LIMIT:
            content = content[:HTML_BODY_TRUNCATE_LIMIT] + "\n\n[Content truncated...]"
        return content
    elif text_stripped:
        return text_body
    else:
        return "[No readable content found]"


def _extract_attachments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract attachment metadata from a Gmail message payload."""
    attachments: list[dict[str, Any]] = []

    def search_parts(part: dict[str, Any]) -> None:
        if part.get("filename") and part.get("body", {}).get("attachmentId"):
            attachments.append(
                {
                    "filename": part["filename"],
                    "mimeType": part.get("mimeType", "application/octet-stream"),
                    "size": part.get("body", {}).get("size", 0),
                    "attachmentId": part["body"]["attachmentId"],
                }
            )
        if "parts" in part:
            for subpart in part["parts"]:
                search_parts(subpart)

    search_parts(payload)
    return attachments


def _extract_headers(
    payload: dict[str, Any], header_names: list[str]
) -> dict[str, str]:
    """Extract specified headers from a Gmail message payload."""
    headers: dict[str, str] = {}
    target_headers = {name.lower(): name for name in header_names}
    for header in payload.get("headers", []):
        header_name_lower = header["name"].lower()
        if header_name_lower in target_headers:
            headers[target_headers[header_name_lower]] = header["value"]
    return headers


def _prepare_gmail_message(
    subject: str,
    body: str,
    to: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    body_format: Literal["plain", "html"] = "plain",
) -> tuple[str, str | None]:
    """Prepare a Gmail message. Returns (raw_message_b64, thread_id)."""
    reply_subject = subject
    if in_reply_to and not subject.lower().startswith("re:"):
        reply_subject = f"Re: {subject}"

    normalized_format = body_format.lower()
    if normalized_format not in {"plain", "html"}:
        raise ValueError("body_format must be either 'plain' or 'html'.")

    message = MIMEText(body, normalized_format)
    message["Subject"] = reply_subject

    if to:
        message["To"] = to
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return raw_message, thread_id


def _generate_gmail_web_url(item_id: str) -> str:
    """Generate Gmail web interface URL for a message or thread ID."""
    return f"https://mail.google.com/mail/u/0/#all/{item_id}"


async def _get_gmail_service():  # type: ignore[no-untyped-def]  # TODO: googleapiclient has no stubs
    global _gmail_service
    if _gmail_service is not None:
        return _gmail_service

    async with _gmail_service_lock:
        if _gmail_service is not None:
            return _gmail_service
        try:
            creds = await asyncio.to_thread(
                get_credentials, DEFAULT_GMAIL_SCOPES, False, False
            )
        except RuntimeError as exc:
            raise RuntimeError(
                "Gmail not authenticated. Run `lifeos-google-auth` to authorize."
            ) from exc

        service = await asyncio.to_thread(
            build, "gmail", "v1", credentials=creds, cache_discovery=False
        )
        _gmail_service = service
        return service


def _format_http_error(tool_name: str, error: HttpError) -> RuntimeError:
    status = getattr(error.resp, "status", None)
    if status in (401, 403):
        return RuntimeError(
            f"Gmail auth error in {tool_name}: {error}. "
            "Run `lifeos-google-auth` to re-authenticate."
        )
    return RuntimeError(f"Gmail API error in {tool_name}: {error}")


async def search_messages(
    query: str,
    page_size: int = 10,
    page_token: str | None = None,
) -> str:
    """Search messages in Gmail. Returns message/thread IDs."""
    service = await _get_gmail_service()

    request_params: dict[str, Any] = {
        "userId": "me",
        "q": query,
        "maxResults": page_size,
    }
    if page_token:
        request_params["pageToken"] = page_token

    try:
        response = await asyncio.to_thread(
            lambda: service.users().messages().list(**request_params).execute()
        )
    except HttpError as error:
        raise _format_http_error("search_messages", error) from error

    messages = response.get("messages", [])
    next_page_token = response.get("nextPageToken")

    if not messages:
        return f"No messages found for query: '{query}'"

    lines = [f"Found {len(messages)} messages matching '{query}':", ""]

    for i, msg in enumerate(messages, 1):
        message_id = msg.get("id", "unknown")
        thread_id = msg.get("threadId", "unknown")
        message_url = _generate_gmail_web_url(message_id) if message_id != "unknown" else "N/A"

        lines.extend([
            f"  {i}. Message ID: {message_id}",
            f"     Web Link: {message_url}",
            f"     Thread ID: {thread_id}",
            "",
        ])

    lines.extend([
        "Use get_gmail_message to read a message, or get_gmail_thread to read a full thread.",
    ])

    if next_page_token:
        lines.append(
            f"\nMore results available. Call search_gmail with page_token='{next_page_token}'"
        )

    return "\n".join(lines)


async def get_message(message_id: str) -> str:
    """Get full content of a specific Gmail message."""
    service = await _get_gmail_service()

    try:
        # Fetch metadata headers
        message_metadata = await asyncio.to_thread(
            lambda: service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=GMAIL_METADATA_HEADERS,
            )
            .execute()
        )

        headers = _extract_headers(
            message_metadata.get("payload", {}), GMAIL_METADATA_HEADERS
        )
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From", "(unknown sender)")
        to = headers.get("To", "")
        cc = headers.get("Cc", "")
        rfc822_msg_id = headers.get("Message-ID", "")

        # Fetch full message for body
        message_full = await asyncio.to_thread(
            lambda: service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
    except HttpError as error:
        raise _format_http_error("get_message", error) from error

    payload = message_full.get("payload", {})
    bodies = _extract_message_bodies(payload)
    body_data = _format_body_content(bodies.get("text", ""), bodies.get("html", ""))

    attachments = _extract_attachments(payload)

    content_lines = [
        f"Subject: {subject}",
        f"From:    {sender}",
        f"Date:    {headers.get('Date', '(unknown date)')}",
    ]

    if rfc822_msg_id:
        content_lines.append(f"Message-ID: {rfc822_msg_id}")
    if to:
        content_lines.append(f"To:      {to}")
    if cc:
        content_lines.append(f"Cc:      {cc}")

    content_lines.append(
        f"Thread ID: {message_metadata.get('threadId', 'unknown')}"
    )
    content_lines.append(f"Web Link: {_generate_gmail_web_url(message_id)}")
    content_lines.append(f"\n--- BODY ---\n{body_data or '[No body found]'}")

    if attachments:
        content_lines.append("\n--- ATTACHMENTS ---")
        for i, att in enumerate(attachments, 1):
            size_kb = att["size"] / 1024
            content_lines.append(
                f"{i}. {att['filename']} ({att['mimeType']}, {size_kb:.1f} KB)"
            )

    return "\n".join(content_lines)


async def get_thread(thread_id: str) -> str:
    """Get all messages in a Gmail thread."""
    service = await _get_gmail_service()

    try:
        thread_response = await asyncio.to_thread(
            lambda: service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
    except HttpError as error:
        raise _format_http_error("get_thread", error) from error

    messages = thread_response.get("messages", [])
    if not messages:
        return f"No messages found in thread '{thread_id}'."

    first_headers = {
        h["name"]: h["value"]
        for h in messages[0].get("payload", {}).get("headers", [])
    }
    thread_subject = first_headers.get("Subject", "(no subject)")

    content_lines = [
        f"Thread ID: {thread_id}",
        f"Subject: {thread_subject}",
        f"Messages: {len(messages)}",
        f"Web Link: {_generate_gmail_web_url(thread_id)}",
        "",
    ]

    for i, message in enumerate(messages, 1):
        headers = {
            h["name"]: h["value"]
            for h in message.get("payload", {}).get("headers", [])
        }
        sender = headers.get("From", "(unknown sender)")
        date = headers.get("Date", "(unknown date)")
        subject = headers.get("Subject", "(no subject)")

        payload = message.get("payload", {})
        bodies = _extract_message_bodies(payload)
        body_data = _format_body_content(
            bodies.get("text", ""), bodies.get("html", "")
        )

        content_lines.extend([
            f"=== Message {i} (ID: {message.get('id', 'unknown')}) ===",
            f"From: {sender}",
            f"Date: {date}",
        ])

        if subject != thread_subject:
            content_lines.append(f"Subject: {subject}")

        content_lines.extend(["", body_data, ""])

    return "\n".join(content_lines)


async def send_message(
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
    service = await _get_gmail_service()

    raw_message, thread_id_final = _prepare_gmail_message(
        subject=subject,
        body=body,
        to=to,
        cc=cc,
        bcc=bcc,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        references=references,
        body_format=body_format,
    )

    send_body: dict[str, Any] = {"raw": raw_message}
    if thread_id_final:
        send_body["threadId"] = thread_id_final

    try:
        sent_message = await asyncio.to_thread(
            lambda: service.users()
            .messages()
            .send(userId="me", body=send_body)
            .execute()
        )
    except HttpError as error:
        raise _format_http_error("send_message", error) from error

    msg_id = sent_message.get("id")
    return f"Email sent. Message ID: {msg_id}"


async def draft_message(
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
    service = await _get_gmail_service()

    raw_message, thread_id_final = _prepare_gmail_message(
        subject=subject,
        body=body,
        to=to,
        cc=cc,
        bcc=bcc,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        references=references,
        body_format=body_format,
    )

    draft_body: dict[str, Any] = {"message": {"raw": raw_message}}
    if thread_id_final:
        draft_body["message"]["threadId"] = thread_id_final

    try:
        created_draft = await asyncio.to_thread(
            lambda: service.users()
            .drafts()
            .create(userId="me", body=draft_body)
            .execute()
        )
    except HttpError as error:
        raise _format_http_error("draft_message", error) from error

    draft_id = created_draft.get("id")
    return f"Draft created. Draft ID: {draft_id}"


async def list_labels() -> str:
    """List all Gmail labels."""
    service = await _get_gmail_service()

    try:
        response = await asyncio.to_thread(
            lambda: service.users().labels().list(userId="me").execute()
        )
    except HttpError as error:
        raise _format_http_error("list_labels", error) from error

    labels = response.get("labels", [])
    if not labels:
        return "No labels found."

    system_labels = []
    user_labels = []

    for label in labels:
        if label.get("type") == "system":
            system_labels.append(label)
        else:
            user_labels.append(label)

    lines = [f"Found {len(labels)} labels:", ""]

    if system_labels:
        lines.append("SYSTEM LABELS:")
        for label in system_labels:
            lines.append(f"  - {label['name']} (ID: {label['id']})")
        lines.append("")

    if user_labels:
        lines.append("USER LABELS:")
        for label in user_labels:
            lines.append(f"  - {label['name']} (ID: {label['id']})")

    return "\n".join(lines)


async def modify_message_labels(
    message_id: str,
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> str:
    """Add or remove labels from a Gmail message."""
    service = await _get_gmail_service()

    if not add_label_ids and not remove_label_ids:
        raise RuntimeError(
            "At least one of add_label_ids or remove_label_ids must be provided."
        )

    modify_body: dict[str, Any] = {}
    if add_label_ids:
        modify_body["addLabelIds"] = add_label_ids
    if remove_label_ids:
        modify_body["removeLabelIds"] = remove_label_ids

    try:
        await asyncio.to_thread(
            lambda: service.users()
            .messages()
            .modify(userId="me", id=message_id, body=modify_body)
            .execute()
        )
    except HttpError as error:
        raise _format_http_error("modify_message_labels", error) from error

    actions = []
    if add_label_ids:
        actions.append(f"Added labels: {', '.join(add_label_ids)}")
    if remove_label_ids:
        actions.append(f"Removed labels: {', '.join(remove_label_ids)}")

    return f"Message labels updated. Message ID: {message_id}\n{'; '.join(actions)}"
