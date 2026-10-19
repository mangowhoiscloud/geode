"""Native MCP failure envelopes never become sent/created/deleted or empty reads (S3, S7)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from core.mcp.base_notification import parse_mcp_result
from core.mcp.calendar_port import CalendarEvent, CalendarReadError
from core.mcp.composite_calendar import CompositeCalendarAdapter
from core.mcp.discord_adapter import DiscordNotificationAdapter
from core.mcp.google_calendar_adapter import GoogleCalendarAdapter
from core.scheduler.calendar_bridge import CalendarSchedulerBridge
from core.tools.calendar_tools import CalendarCreateEventTool, CalendarListEventsTool
from core.tools.output_tools import SendNotificationTool

_IS_ERROR = {"isError": True, "content": [{"type": "text", "text": "permission denied"}]}


class _Manager:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def check_health(self) -> dict[str, bool]:
        return {"discord": True, "google-calendar": True}

    async def acall_tool(self, *_args: Any) -> Any:
        return self.payload


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (_IS_ERROR, {"error": "permission denied"}),
        ({"isError": True, "content": []}, {"error": "MCP tool reported an error"}),
        ({"error": "transport closed"}, {"error": "transport closed"}),
        ({"content": [{"type": "text", "text": '{"id": "m1"}'}]}, {"id": "m1"}),
        ({"structuredContent": {"id": "s1"}, "content": []}, {"id": "s1"}),
        ({"content": [{"type": "text", "text": "sent ok"}]}, {"text": "sent ok"}),
        ({"id": "plain"}, {"id": "plain"}),
        ("not a dict", None),
    ],
)
def test_parse_mcp_result_projection(raw: Any, expected: dict[str, Any] | None) -> None:
    parsed = parse_mcp_result(raw)
    if expected is None:
        assert "error" in parsed
    else:
        assert parsed == expected


def test_notification_error_envelope_is_not_sent() -> None:
    tool = SendNotificationTool(DiscordNotificationAdapter(manager=_Manager(_IS_ERROR)))
    result = asyncio.run(tool.aexecute(channel="discord", recipient="r", message="never sent"))
    assert result["result"]["sent"] is False
    assert "permission denied" in result["error"]  # visible to the executor and hooks


def test_notification_success_keeps_message_id() -> None:
    manager = _Manager({"content": [{"type": "text", "text": '{"id": "msg_9"}'}]})
    tool = SendNotificationTool(DiscordNotificationAdapter(manager=manager))
    result = asyncio.run(tool.aexecute(channel="discord", recipient="r", message="hi"))
    assert "error" not in result
    assert result["result"]["sent"] is True and result["result"]["message_id"] == "msg_9"


def test_calendar_create_error_envelope_or_missing_id_is_not_created() -> None:
    start = "2026-10-15T12:00:00"
    for payload in (_IS_ERROR, {"content": [{"type": "text", "text": "{}"}]}):
        tool = CalendarCreateEventTool(GoogleCalendarAdapter(manager=_Manager(payload)))
        result = asyncio.run(tool.aexecute(title="never created", start_datetime=start))
        assert "error" in result, payload
        assert "result" not in result


def test_calendar_delete_error_envelope_is_false() -> None:
    adapter = GoogleCalendarAdapter(manager=_Manager(_IS_ERROR))
    assert asyncio.run(adapter.adelete_event("evt")) is False


def test_calendar_read_failure_is_an_error_not_an_empty_schedule() -> None:
    for payload in (_IS_ERROR, {"error": "unauthorized"}):
        tool = CalendarListEventsTool(GoogleCalendarAdapter(manager=_Manager(payload)))
        result = asyncio.run(tool.aexecute())
        assert "error" in result and "result" not in result
        assert "unknown, not empty" in result["hint"]


class _Source:
    def __init__(self, events: list[CalendarEvent] | None = None, fail: bool = False) -> None:
        self.events = events or []
        self.fail = fail

    async def ais_available(self) -> bool:
        return True

    async def alist_events(self, **_kwargs: Any) -> list[CalendarEvent]:
        if self.fail:
            raise RuntimeError("remote denied request")
        return self.events


def _event(title: str) -> CalendarEvent:
    start = datetime.now(UTC) + timedelta(hours=1)
    return CalendarEvent(
        event_id=title, title=title, start=start, end=start, source="google", is_geode=True
    )


def test_composite_all_sources_failed_is_an_error() -> None:
    composite = CompositeCalendarAdapter([_Source(fail=True), _Source(fail=True)])
    with pytest.raises(CalendarReadError) as caught:
        asyncio.run(composite.alist_events())
    assert caught.value.partial is False
    result = asyncio.run(CalendarListEventsTool(composite).aexecute())
    assert "error" in result


def test_composite_partial_failure_is_explicit() -> None:
    composite = CompositeCalendarAdapter([_Source([_event("kept")]), _Source(fail=True)])
    result = asyncio.run(CalendarListEventsTool(composite).aexecute())["result"]
    assert result["count"] == 1
    assert result["partial"] is True
    assert len(result["failed_sources"]) == 1


def test_composite_success_with_no_events_stays_a_valid_empty_schedule() -> None:
    result = asyncio.run(CalendarListEventsTool(CompositeCalendarAdapter([_Source()])).aexecute())
    assert result["result"]["count"] == 0
    assert "partial" not in result["result"]


def test_bridge_does_not_push_duplicates_when_existing_events_cannot_be_read() -> None:
    class _Scheduler:
        def list_jobs(self) -> list[Any]:
            from core.scheduler import Schedule, ScheduledJob, ScheduleKind

            return [
                ScheduledJob(
                    job_id="j",
                    name="job",
                    schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
                    action="x",
                )
            ]

    class _Calendar(_Source):
        created: list[str] = []

        async def acreate_event(self, title: str, *_args: Any, **_kwargs: Any) -> CalendarEvent:
            self.created.append(title)
            return _event(title)

    calendar = _Calendar(fail=True)
    pushed, errors = asyncio.run(
        CalendarSchedulerBridge(_Scheduler(), calendar)._push_to_calendar()
    )
    assert pushed == 0 and calendar.created == []
    assert errors and "could not be read" in errors[0]
