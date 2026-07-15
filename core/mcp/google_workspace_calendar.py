"""Direct Google Calendar adapter using the /login google credential store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from core.mcp.calendar_port import CalendarEvent
from core.mcp.google_workspace_client import (
    GoogleWorkspaceClient,
    get_google_workspace_client,
)

CALENDAR_READ_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned.readonly"
CALENDAR_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
_CALENDAR_SCOPES = (CALENDAR_READ_SCOPE, CALENDAR_WRITE_SCOPE)


class GoogleWorkspaceCalendarAdapter:
    """CalendarPort implementation independent of an external MCP server."""

    def __init__(self, client: GoogleWorkspaceClient | None = None) -> None:
        self._client = client or get_google_workspace_client()

    async def ais_available(self) -> bool:
        return await self.acan_read()

    async def acan_read(self) -> bool:
        """Return whether the active account can read owned events."""
        return self._client.has_active_account() and self._client.has_any_scope(_CALENDAR_SCOPES)

    async def acan_write(self) -> bool:
        """Return whether the active account can mutate owned events."""
        return self._client.has_active_account() and self._client.has_scopes(
            (CALENDAR_WRITE_SCOPE,)
        )

    async def alist_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        calendar_name: str | None = None,
        max_results: int = 20,
    ) -> list[CalendarEvent]:
        calendar_id = quote(calendar_name or "primary", safe="")
        now = datetime.now(UTC)
        payload = await self._client.request_json(
            "GET",
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            required_scopes=_CALENDAR_SCOPES,
            any_scope=True,
            params={
                "timeMin": (start or now).isoformat(),
                "timeMax": (end or now + timedelta(days=7)).isoformat(),
                "maxResults": max(1, min(int(max_results), 2500)),
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        events: list[CalendarEvent] = []
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            start_at = _parse_google_datetime(item.get("start"))
            end_at = _parse_google_datetime(item.get("end"))
            if start_at is None or end_at is None:
                continue
            title = str(item.get("summary", ""))
            organizer = item.get("organizer")
            organizer_name = (
                str(organizer.get("displayName") or organizer.get("email") or "")
                if isinstance(organizer, dict)
                else ""
            )
            events.append(
                CalendarEvent(
                    event_id=str(item.get("id", "")),
                    title=title,
                    start=start_at,
                    end=end_at,
                    description=str(item.get("description", "")),
                    location=str(item.get("location", "")),
                    source="google",
                    calendar_name=calendar_name or organizer_name or "primary",
                    is_geode=title.startswith("[GEODE]"),
                    metadata={
                        "html_link": str(item.get("htmlLink", "")),
                        "status": str(item.get("status", "")),
                    },
                )
            )
        return events

    async def acreate_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        *,
        description: str = "",
        location: str = "",
        calendar_name: str | None = None,
    ) -> CalendarEvent:
        calendar_id = quote(calendar_name or "primary", safe="")
        body: dict[str, object] = {
            "summary": title,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        payload = await self._client.request_json(
            "POST",
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            required_scopes=(CALENDAR_WRITE_SCOPE,),
            json_body=body,
        )
        return CalendarEvent(
            event_id=str(payload.get("id", "")),
            title=str(payload.get("summary", title)),
            start=_parse_google_datetime(payload.get("start")) or start,
            end=_parse_google_datetime(payload.get("end")) or end,
            description=str(payload.get("description", description)),
            location=str(payload.get("location", location)),
            source="google",
            calendar_name=calendar_name or "primary",
            is_geode=title.startswith("[GEODE]"),
            metadata={"html_link": str(payload.get("htmlLink", ""))},
        )

    async def adelete_event(self, event_id: str) -> bool:
        safe_event_id = quote(event_id, safe="")
        await self._client.request(
            "DELETE",
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{safe_event_id}",
            required_scopes=(CALENDAR_WRITE_SCOPE,),
        )
        return True

    async def alist_calendars(self) -> list[str]:
        return ["primary"] if await self.ais_available() else []


def _parse_google_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("dateTime") or raw.get("date")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
