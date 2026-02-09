import asyncio
import datetime
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Union

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from lifeos.google_auth import DEFAULT_CALENDAR_SCOPES, get_credentials

logger = logging.getLogger(__name__)

_calendar_service = None
_calendar_service_lock = asyncio.Lock()


def _user_label(user_google_email: Optional[str]) -> str:
    return user_google_email or os.getenv("GOOGLE_USER_EMAIL") or "the authenticated account"


async def _get_calendar_service():
    global _calendar_service
    if _calendar_service is not None:
        return _calendar_service

    async with _calendar_service_lock:
        if _calendar_service is not None:
            return _calendar_service
        try:
            creds = await asyncio.to_thread(
                get_credentials, DEFAULT_CALENDAR_SCOPES, False, False
            )
        except RuntimeError as exc:
            raise RuntimeError(
                "Google Calendar not authenticated. Run `lifeos-google-auth` to authorize."
            ) from exc

        service = await asyncio.to_thread(
            build, "calendar", "v3", credentials=creds, cache_discovery=False
        )
        _calendar_service = service
        return service


def _format_http_error(tool_name: str, error: HttpError) -> RuntimeError:
    status = getattr(error.resp, "status", None)
    if status in (401, 403):
        return RuntimeError(
            f"Google Calendar auth error in {tool_name}: {error}. "
            "Run `lifeos-google-auth` to re-authenticate."
        )
    return RuntimeError(f"Google Calendar API error in {tool_name}: {error}")


def _parse_reminders_json(
    reminders_input: Optional[Union[str, List[Dict[str, Any]]]], function_name: str
) -> List[Dict[str, Any]]:
    if not reminders_input:
        return []

    if isinstance(reminders_input, str):
        try:
            reminders = json.loads(reminders_input)
            if not isinstance(reminders, list):
                logger.warning(
                    "[%s] Reminders must be a JSON array, got %s",
                    function_name,
                    type(reminders).__name__,
                )
                return []
        except json.JSONDecodeError as e:
            logger.warning("[%s] Invalid JSON for reminders: %s", function_name, e)
            return []
    elif isinstance(reminders_input, list):
        reminders = reminders_input
    else:
        logger.warning(
            "[%s] Reminders must be a JSON string or list, got %s",
            function_name,
            type(reminders_input).__name__,
        )
        return []

    if len(reminders) > 5:
        logger.warning(
            "[%s] More than 5 reminders provided, truncating to first 5",
            function_name,
        )
        reminders = reminders[:5]

    validated_reminders = []
    for reminder in reminders:
        if (
            not isinstance(reminder, dict)
            or "method" not in reminder
            or "minutes" not in reminder
        ):
            logger.warning("[%s] Invalid reminder format: %s", function_name, reminder)
            continue

        method = reminder["method"].lower()
        if method not in ["popup", "email"]:
            logger.warning(
                "[%s] Invalid reminder method '%s', skipping",
                function_name,
                method,
            )
            continue

        minutes = reminder["minutes"]
        if not isinstance(minutes, int) or minutes < 0 or minutes > 40320:
            logger.warning(
                "[%s] Invalid reminder minutes '%s', skipping",
                function_name,
                minutes,
            )
            continue

        validated_reminders.append({"method": method, "minutes": minutes})

    return validated_reminders


def _apply_transparency_if_valid(
    event_body: Dict[str, Any], transparency: Optional[str], function_name: str
) -> None:
    if transparency is None:
        return

    valid_transparency_values = ["opaque", "transparent"]
    if transparency in valid_transparency_values:
        event_body["transparency"] = transparency
        logger.info("[%s] Set transparency to '%s'", function_name, transparency)
    else:
        logger.warning(
            "[%s] Invalid transparency value '%s', skipping",
            function_name,
            transparency,
        )


def _apply_visibility_if_valid(
    event_body: Dict[str, Any], visibility: Optional[str], function_name: str
) -> None:
    if visibility is None:
        return

    valid_visibility_values = ["default", "public", "private", "confidential"]
    if visibility in valid_visibility_values:
        event_body["visibility"] = visibility
        logger.info("[%s] Set visibility to '%s'", function_name, visibility)
    else:
        logger.warning(
            "[%s] Invalid visibility value '%s', skipping",
            function_name,
            visibility,
        )


def _format_attendee_details(
    attendees: List[Dict[str, Any]], indent: str = "  "
) -> str:
    if not attendees:
        return "None"

    attendee_details_list = []
    for attendee in attendees:
        email = attendee.get("email", "unknown")
        response_status = attendee.get("responseStatus", "unknown")
        optional = attendee.get("optional", False)
        organizer = attendee.get("organizer", False)

        detail_parts = [f"{email}: {response_status}"]
        if organizer:
            detail_parts.append("(organizer)")
        if optional:
            detail_parts.append("(optional)")

        attendee_details_list.append(" ".join(detail_parts))

    return f"\n{indent}".join(attendee_details_list)


def _format_attachment_details(
    attachments: List[Dict[str, Any]], indent: str = "  "
) -> str:
    if not attachments:
        return "None"

    attachment_details_list = []
    for att in attachments:
        title = att.get("title", "Untitled")
        file_url = att.get("fileUrl", "No URL")
        file_id = att.get("fileId", "No ID")
        mime_type = att.get("mimeType", "Unknown")

        attachment_info = (
            f"{title}\n"
            f"{indent}File URL: {file_url}\n"
            f"{indent}File ID: {file_id}\n"
            f"{indent}MIME Type: {mime_type}"
        )
        attachment_details_list.append(attachment_info)

    return f"\n{indent}".join(attachment_details_list)


def _correct_time_format_for_api(
    time_str: Optional[str], param_name: str
) -> Optional[str]:
    if not time_str:
        return None

    logger.info(
        "_correct_time_format_for_api: Processing %s with value '%s'",
        param_name,
        time_str,
    )

    if len(time_str) == 10 and time_str.count("-") == 2:
        try:
            datetime.datetime.strptime(time_str, "%Y-%m-%d")
            formatted = f"{time_str}T00:00:00Z"
            logger.info(
                "Formatting date-only %s '%s' to RFC3339: '%s'",
                param_name,
                time_str,
                formatted,
            )
            return formatted
        except ValueError:
            logger.warning(
                "%s '%s' looks like a date but is not valid YYYY-MM-DD. Using as is.",
                param_name,
                time_str,
            )
            return time_str

    if (
        len(time_str) == 19
        and time_str[10] == "T"
        and time_str.count(":") == 2
        and not (
            time_str.endswith("Z") or ("+" in time_str[10:]) or ("-" in time_str[10:])
        )
    ):
        try:
            datetime.datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S")
            logger.info(
                "Formatting %s '%s' by appending 'Z' for UTC.",
                param_name,
                time_str,
            )
            return time_str + "Z"
        except ValueError:
            logger.warning(
                "%s '%s' looks like it needs 'Z' but is not valid YYYY-MM-DDTHH:MM:SS. Using as is.",
                param_name,
                time_str,
            )
            return time_str

    logger.info("%s '%s' doesn't need formatting, using as is.", param_name, time_str)
    return time_str


def _normalize_attendees(
    attendees: Optional[Union[List[str], List[Dict[str, Any]]]]
) -> Optional[List[Dict[str, Any]]]:
    if attendees is None:
        return None

    normalized = []
    for attendee in attendees:
        if isinstance(attendee, str):
            normalized.append({"email": attendee})
        elif isinstance(attendee, dict) and "email" in attendee:
            normalized.append(attendee)
        else:
            logger.warning("[_normalize_attendees] Invalid attendee format: %s", attendee)
    return normalized if normalized else None


async def list_calendars(user_google_email: Optional[str] = None) -> str:
    user_label = _user_label(user_google_email)
    service = await _get_calendar_service()

    try:
        calendar_list_response = await asyncio.to_thread(
            lambda: service.calendarList().list().execute()
        )
    except HttpError as error:
        raise _format_http_error("list_calendars", error) from error

    items = calendar_list_response.get("items", [])
    if not items:
        return f"No calendars found for {user_label}."

    calendars_summary_list = [
        f'- "{cal.get("summary", "No Summary")}"'
        f'{" (Primary)" if cal.get("primary") else ""} (ID: {cal["id"]})'
        for cal in items
    ]
    text_output = (
        f"Successfully listed {len(items)} calendars for {user_label}:\n"
        + "\n".join(calendars_summary_list)
    )
    return text_output


async def get_events(
    user_google_email: Optional[str] = None,
    calendar_id: str = "primary",
    event_id: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 25,
    query: Optional[str] = None,
    detailed: bool = False,
    include_attachments: bool = False,
) -> str:
    user_label = _user_label(user_google_email)
    service = await _get_calendar_service()

    try:
        if event_id:
            event = await asyncio.to_thread(
                lambda: service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )
            items = [event]
        else:
            formatted_time_min = _correct_time_format_for_api(time_min, "time_min")
            if formatted_time_min:
                effective_time_min = formatted_time_min
            else:
                utc_now = datetime.datetime.now(datetime.timezone.utc)
                effective_time_min = utc_now.isoformat().replace("+00:00", "Z")

            effective_time_max = _correct_time_format_for_api(time_max, "time_max")

            request_params = {
                "calendarId": calendar_id,
                "timeMin": effective_time_min,
                "timeMax": effective_time_max,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }

            if query:
                request_params["q"] = query

            events_result = await asyncio.to_thread(
                lambda: service.events().list(**request_params).execute()
            )
            items = events_result.get("items", [])
    except HttpError as error:
        raise _format_http_error("get_events", error) from error

    if not items:
        if event_id:
            return (
                f"Event with ID '{event_id}' not found in calendar '{calendar_id}' "
                f"for {user_label}."
            )
        return (
            f"No events found in calendar '{calendar_id}' for {user_label} "
            "for the specified time range."
        )

    if event_id and detailed:
        item = items[0]
        summary = item.get("summary", "No Title")
        start = item["start"].get("dateTime", item["start"].get("date"))
        end = item["end"].get("dateTime", item["end"].get("date"))
        link = item.get("htmlLink", "No Link")
        description = item.get("description", "No Description")
        location = item.get("location", "No Location")
        color_id = item.get("colorId", "None")
        attendees = item.get("attendees", [])
        attendee_emails = (
            ", ".join([a.get("email", "") for a in attendees]) if attendees else "None"
        )
        attendee_details_str = _format_attendee_details(attendees, indent="  ")

        event_details = (
            "Event Details:\n"
            f"- Title: {summary}\n"
            f"- Starts: {start}\n"
            f"- Ends: {end}\n"
            f"- Description: {description}\n"
            f"- Location: {location}\n"
            f"- Color ID: {color_id}\n"
            f"- Attendees: {attendee_emails}\n"
            f"- Attendee Details: {attendee_details_str}\n"
        )

        if include_attachments:
            attachments = item.get("attachments", [])
            attachment_details_str = _format_attachment_details(
                attachments, indent="  "
            )
            event_details += f"- Attachments: {attachment_details_str}\n"

        event_details += f"- Event ID: {event_id}\n- Link: {link}"
        return event_details

    event_details_list = []
    for item in items:
        summary = item.get("summary", "No Title")
        start_time = item["start"].get("dateTime", item["start"].get("date"))
        end_time = item["end"].get("dateTime", item["end"].get("date"))
        link = item.get("htmlLink", "No Link")
        item_event_id = item.get("id", "No ID")

        if detailed:
            description = item.get("description", "No Description")
            location = item.get("location", "No Location")
            attendees = item.get("attendees", [])
            attendee_emails = (
                ", ".join([a.get("email", "") for a in attendees])
                if attendees
                else "None"
            )
            attendee_details_str = _format_attendee_details(attendees, indent="    ")

            event_detail_parts = (
                f'- "{summary}" (Starts: {start_time}, Ends: {end_time})\n'
                f"  Description: {description}\n"
                f"  Location: {location}\n"
                f"  Attendees: {attendee_emails}\n"
                f"  Attendee Details: {attendee_details_str}\n"
            )

            if include_attachments:
                attachments = item.get("attachments", [])
                attachment_details_str = _format_attachment_details(
                    attachments, indent="    "
                )
                event_detail_parts += f"  Attachments: {attachment_details_str}\n"

            event_detail_parts += f"  ID: {item_event_id} | Link: {link}"
            event_details_list.append(event_detail_parts)
        else:
            event_details_list.append(
                f'- "{summary}" (Starts: {start_time}, Ends: {end_time}) '
                f"ID: {item_event_id} | Link: {link}"
            )

    if event_id:
        text_output = (
            f"Successfully retrieved event from calendar '{calendar_id}' "
            f"for {user_label}:\n"
            + "\n".join(event_details_list)
        )
    else:
        text_output = (
            f"Successfully retrieved {len(items)} events from calendar '{calendar_id}' "
            f"for {user_label}:\n"
            + "\n".join(event_details_list)
        )

    return text_output


async def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    user_google_email: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    timezone: Optional[str] = None,
    attachments: Optional[List[str]] = None,
    add_google_meet: bool = False,
    reminders: Optional[Union[str, List[Dict[str, Any]]]] = None,
    use_default_reminders: bool = True,
    transparency: Optional[str] = None,
    visibility: Optional[str] = None,
) -> str:
    user_label = _user_label(user_google_email)
    service = await _get_calendar_service()

    if attachments and isinstance(attachments, str):
        attachments = [a.strip() for a in attachments.split(",") if a.strip()]

    event_body: Dict[str, Any] = {
        "summary": summary,
        "start": (
            {"date": start_time} if "T" not in start_time else {"dateTime": start_time}
        ),
        "end": ({"date": end_time} if "T" not in end_time else {"dateTime": end_time}),
    }
    if location:
        event_body["location"] = location
    if description:
        event_body["description"] = description
    if timezone:
        if "dateTime" in event_body["start"]:
            event_body["start"]["timeZone"] = timezone
        if "dateTime" in event_body["end"]:
            event_body["end"]["timeZone"] = timezone
    if attendees:
        event_body["attendees"] = [{"email": email} for email in attendees]

    if reminders is not None or not use_default_reminders:
        effective_use_default = use_default_reminders and reminders is None
        reminder_data = {"useDefault": effective_use_default}
        if reminders is not None:
            validated_reminders = _parse_reminders_json(reminders, "create_event")
            if validated_reminders:
                reminder_data["overrides"] = validated_reminders
        event_body["reminders"] = reminder_data

    _apply_transparency_if_valid(event_body, transparency, "create_event")
    _apply_visibility_if_valid(event_body, visibility, "create_event")

    if add_google_meet:
        request_id = str(uuid.uuid4())
        event_body["conferenceData"] = {
            "createRequest": {
                "requestId": request_id,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    if attachments:
        event_body["attachments"] = []
        for att in attachments:
            file_id = None
            file_url = att
            if att.startswith("https://"):
                match = re.search(r"(?:/d/|/file/d/|id=)([\w-]+)", att)
                file_id = match.group(1) if match else None
                if file_id:
                    file_url = f"https://drive.google.com/open?id={file_id}"
            else:
                file_id = att
                file_url = f"https://drive.google.com/open?id={file_id}"

            title = "Drive Attachment"
            if file_id:
                title = file_id

            event_body["attachments"].append(
                {
                    "fileUrl": file_url,
                    "title": title,
                    "mimeType": "application/vnd.google-apps.drive-sdk",
                }
            )

    try:
        if attachments:
            created_event = await asyncio.to_thread(
                lambda: service.events()
                .insert(
                    calendarId=calendar_id,
                    body=event_body,
                    supportsAttachments=True,
                    conferenceDataVersion=1 if add_google_meet else 0,
                )
                .execute()
            )
        else:
            created_event = await asyncio.to_thread(
                lambda: service.events()
                .insert(
                    calendarId=calendar_id,
                    body=event_body,
                    conferenceDataVersion=1 if add_google_meet else 0,
                )
                .execute()
            )
    except HttpError as error:
        raise _format_http_error("create_event", error) from error

    link = created_event.get("htmlLink", "No link available")
    confirmation_message = (
        f"Successfully created event '{created_event.get('summary', summary)}' "
        f"for {user_label}. Link: {link}"
    )

    if add_google_meet and "conferenceData" in created_event:
        conference_data = created_event["conferenceData"]
        if "entryPoints" in conference_data:
            for entry_point in conference_data["entryPoints"]:
                if entry_point.get("entryPointType") == "video":
                    meet_link = entry_point.get("uri", "")
                    if meet_link:
                        confirmation_message += f" Google Meet: {meet_link}"
                        break

    return confirmation_message


async def modify_event(
    event_id: str,
    calendar_id: str = "primary",
    user_google_email: Optional[str] = None,
    summary: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[Union[List[str], List[Dict[str, Any]]]] = None,
    timezone: Optional[str] = None,
    add_google_meet: Optional[bool] = None,
    reminders: Optional[Union[str, List[Dict[str, Any]]]] = None,
    use_default_reminders: Optional[bool] = None,
    transparency: Optional[str] = None,
    visibility: Optional[str] = None,
    color_id: Optional[str] = None,
) -> str:
    user_label = _user_label(user_google_email)
    service = await _get_calendar_service()

    event_body: Dict[str, Any] = {}
    if summary is not None:
        event_body["summary"] = summary
    if start_time is not None:
        event_body["start"] = (
            {"date": start_time} if "T" not in start_time else {"dateTime": start_time}
        )
        if timezone is not None and "dateTime" in event_body["start"]:
            event_body["start"]["timeZone"] = timezone
    if end_time is not None:
        event_body["end"] = (
            {"date": end_time} if "T" not in end_time else {"dateTime": end_time}
        )
        if timezone is not None and "dateTime" in event_body["end"]:
            event_body["end"]["timeZone"] = timezone
    if description is not None:
        event_body["description"] = description
    if location is not None:
        event_body["location"] = location

    normalized_attendees = _normalize_attendees(attendees)
    if normalized_attendees is not None:
        event_body["attendees"] = normalized_attendees

    if color_id is not None:
        event_body["colorId"] = color_id

    if reminders is not None or use_default_reminders is not None:
        reminder_data: Dict[str, Any] = {}
        if use_default_reminders is not None:
            reminder_data["useDefault"] = use_default_reminders
        else:
            try:
                existing_event = await asyncio.to_thread(
                    lambda: service.events()
                    .get(calendarId=calendar_id, eventId=event_id)
                    .execute()
                )
                reminder_data["useDefault"] = existing_event.get("reminders", {}).get(
                    "useDefault", True
                )
            except HttpError:
                reminder_data["useDefault"] = True

        if reminders is not None:
            if reminder_data.get("useDefault", False):
                reminder_data["useDefault"] = False

            validated_reminders = _parse_reminders_json(reminders, "modify_event")
            if validated_reminders:
                reminder_data["overrides"] = validated_reminders

        event_body["reminders"] = reminder_data

    _apply_transparency_if_valid(event_body, transparency, "modify_event")
    _apply_visibility_if_valid(event_body, visibility, "modify_event")

    if timezone is not None and "start" not in event_body and "end" not in event_body:
        logger.warning(
            "[modify_event] Timezone provided but start_time and end_time are missing."
        )

    if add_google_meet is not None:
        if add_google_meet:
            request_id = str(uuid.uuid4())
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": request_id,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        else:
            event_body["conferenceData"] = {}

    if not event_body:
        raise RuntimeError("No fields provided to modify the event.")

    try:
        updated_event = await asyncio.to_thread(
            lambda: service.events()
            .patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=event_body,
                conferenceDataVersion=1,
            )
            .execute()
        )
    except HttpError as error:
        if getattr(error.resp, "status", None) == 404:
            raise RuntimeError(
                f"Event not found. The event with ID '{event_id}' could not be found "
                f"in calendar '{calendar_id}'."
            ) from error
        raise _format_http_error("modify_event", error) from error

    link = updated_event.get("htmlLink", "No link available")
    confirmation_message = (
        f"Successfully modified event '{updated_event.get('summary', summary)}' "
        f"(ID: {event_id}) for {user_label}. Link: {link}"
    )

    if add_google_meet is True and "conferenceData" in updated_event:
        conference_data = updated_event["conferenceData"]
        if "entryPoints" in conference_data:
            for entry_point in conference_data["entryPoints"]:
                if entry_point.get("entryPointType") == "video":
                    meet_link = entry_point.get("uri", "")
                    if meet_link:
                        confirmation_message += f" Google Meet: {meet_link}"
                        break
    elif add_google_meet is False:
        confirmation_message += " (Google Meet removed)"

    return confirmation_message


async def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    user_google_email: Optional[str] = None,
) -> str:
    user_label = _user_label(user_google_email)
    service = await _get_calendar_service()

    try:
        await asyncio.to_thread(
            lambda: service.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute()
        )
    except HttpError as error:
        if getattr(error.resp, "status", None) == 404:
            raise RuntimeError(
                f"Event not found. The event with ID '{event_id}' could not be found "
                f"in calendar '{calendar_id}'."
            ) from error
        raise _format_http_error("delete_event", error) from error

    try:
        await asyncio.to_thread(
            lambda: service.events()
            .delete(calendarId=calendar_id, eventId=event_id)
            .execute()
        )
    except HttpError as error:
        raise _format_http_error("delete_event", error) from error

    return (
        f"Successfully deleted event (ID: {event_id}) from calendar '{calendar_id}' "
        f"for {user_label}."
    )
