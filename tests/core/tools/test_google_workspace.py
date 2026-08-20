"""Google Workspace tool contracts without live Google API calls."""

from __future__ import annotations

import asyncio
import base64
from email import policy
from email.parser import BytesParser
from typing import Any

import httpx
import pytest
from core.mcp.google_workspace_client import GoogleWorkspaceAuthError
from core.tools.google_capabilities import google_scopes_for_tool
from core.tools.google_workspace import (
    GmailSearchTool,
    GmailSendTool,
    GoogleContactsListTool,
    GoogleDocsReadTool,
    GoogleDocsWriteTool,
    GoogleDriveCreateTool,
    GoogleDriveSearchTool,
    GoogleSheetsReadTool,
    GoogleSheetsWriteTool,
    GoogleTasksListTool,
    GoogleTasksWriteTool,
)


class StubGoogleClient:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def _next(self) -> object:
        if not self.responses:
            raise AssertionError("Unexpected Google API call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self._next()
        assert isinstance(response, dict)
        return response

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self._next()
        if isinstance(response, httpx.Response):
            return response
        assert isinstance(response, dict)
        return httpx.Response(200, json=response)


@pytest.mark.parametrize(
    "tool_cls,expected_name",
    [
        (GmailSearchTool, "gmail_search"),
        (GmailSendTool, "gmail_send"),
        (GoogleDriveSearchTool, "google_drive_search"),
        (GoogleDriveCreateTool, "google_drive_create"),
        (GoogleDocsReadTool, "google_docs_read"),
        (GoogleDocsWriteTool, "google_docs_write"),
        (GoogleSheetsReadTool, "google_sheets_read"),
        (GoogleSheetsWriteTool, "google_sheets_write"),
        (GoogleTasksListTool, "google_tasks_list"),
        (GoogleTasksWriteTool, "google_tasks_write"),
        (GoogleContactsListTool, "google_contacts_list"),
    ],
)
def test_tool_surface(tool_cls: type[Any], expected_name: str) -> None:
    tool = tool_cls(StubGoogleClient())
    assert tool.name == expected_name
    assert tool.parameters["type"] == "object"


def test_gmail_search_returns_bounded_plain_text() -> None:
    body = base64.urlsafe_b64encode(b"hello world").decode().rstrip("=")
    client = StubGoogleClient(
        {"messages": [{"id": "m1"}], "resultSizeEstimate": 1},
        {
            "id": "m1",
            "threadId": "t1",
            "snippet": "hello",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Subject"},
                    {"name": "From", "value": "sender@example.com"},
                ],
                "body": {"data": body},
            },
        },
    )
    result = asyncio.run(
        GmailSearchTool(client).aexecute(
            query="newer_than:1d",
            include_body=True,
            max_body_chars=5,
        )
    )
    message = result["result"]["messages"][0]
    assert message["subject"] == "Subject"
    assert message["body"] == "hello"
    assert message["body_truncated"] is True
    assert client.calls[0]["required_scopes"] == google_scopes_for_tool("gmail_search")


def test_gmail_send_builds_rfc_message_and_rejects_header_injection() -> None:
    client = StubGoogleClient({"id": "sent-1", "threadId": "thread-1"})
    result = asyncio.run(
        GmailSendTool(client).aexecute(
            to="reader@example.com",
            subject="Hello",
            body="Body text",
            cc="copy@example.com",
        )
    )
    assert result["result"]["sent"] is True
    raw = client.calls[0]["json_body"]["raw"]
    decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    message = BytesParser(policy=policy.default).parsebytes(decoded)
    assert message["To"] == "reader@example.com"
    assert message["Subject"] == "Hello"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Body text"
    assert client.calls[0]["required_scopes"] == google_scopes_for_tool("gmail_send", write=True)

    rejected = asyncio.run(
        GmailSendTool(StubGoogleClient()).aexecute(
            to="reader@example.com\nBcc: attacker@example.com",
            subject="Hello",
            body="Body text",
        )
    )
    assert rejected["error_type"] == "validation"


def test_drive_search_and_create_use_drive_file_scope() -> None:
    search_client = StubGoogleClient(
        {
            "files": [
                {
                    "id": "f1",
                    "name": "Report",
                    "mimeType": "text/plain",
                    "owners": [{"displayName": "User", "emailAddress": "u@example.com"}],
                }
            ]
        }
    )
    result = asyncio.run(GoogleDriveSearchTool(search_client).aexecute(query="Report"))
    assert result["result"]["files"][0]["id"] == "f1"
    assert "name contains 'Report'" in search_client.calls[0]["params"]["q"]
    assert search_client.calls[0]["required_scopes"] == google_scopes_for_tool(
        "google_drive_search"
    )

    create_client = StubGoogleClient(
        {"id": "folder-1", "name": "Reports", "mimeType": "application/vnd.google-apps.folder"}
    )
    created = asyncio.run(
        GoogleDriveCreateTool(create_client).aexecute(kind="folder", name="Reports")
    )
    assert created["result"]["created"] is True
    assert create_client.calls[0]["json_body"]["mimeType"].endswith("folder")
    assert create_client.calls[0]["required_scopes"] == google_scopes_for_tool(
        "google_drive_create", write=True
    )


def test_docs_read_and_append_contracts() -> None:
    read_client = StubGoogleClient(
        {
            "documentId": "doc-1",
            "title": "Notes",
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [{"textRun": {"content": "abcdef"}}],
                        }
                    }
                ]
            },
        }
    )
    result = asyncio.run(GoogleDocsReadTool(read_client).aexecute(document_id="doc-1", max_chars=3))
    assert result["result"]["text"] == "abc"
    assert result["result"]["truncated"] is True
    assert read_client.calls[0]["required_scopes"] == google_scopes_for_tool("google_docs_read")

    write_client = StubGoogleClient(
        {"body": {"content": [{"endIndex": 12}]}},
        {},
    )
    written = asyncio.run(
        GoogleDocsWriteTool(write_client).aexecute(
            action="append",
            document_id="doc-1",
            text="more",
        )
    )
    assert written["result"]["updated"] is True
    insert = write_client.calls[1]["json_body"]["requests"][0]["insertText"]
    assert insert == {"location": {"index": 11}, "text": "more"}
    assert all(
        call["required_scopes"] == google_scopes_for_tool("google_docs_write", write=True)
        for call in write_client.calls
    )


def test_sheets_tasks_and_contacts_return_structured_results() -> None:
    sheets = StubGoogleClient({"range": "Sheet1!A1:B2", "values": [[1, 2], [3, 4]]})
    sheet_result = asyncio.run(
        GoogleSheetsReadTool(sheets).aexecute(
            spreadsheet_id="sheet-1",
            range="Sheet1!A1:B2",
        )
    )
    assert sheet_result["result"]["row_count"] == 2
    assert sheets.calls[0]["required_scopes"] == google_scopes_for_tool("google_sheets_read")

    tasks = StubGoogleClient(
        {"items": [{"id": "task-1", "title": "Review", "status": "needsAction"}]}
    )
    task_result = asyncio.run(GoogleTasksListTool(tasks).aexecute())
    assert task_result["result"]["tasks"][0]["title"] == "Review"
    assert tasks.calls[0]["any_scope"] is True
    assert tasks.calls[0]["required_scopes"] == google_scopes_for_tool("google_tasks_list")

    contacts = StubGoogleClient(
        {
            "connections": [
                {
                    "resourceName": "people/c1",
                    "names": [{"displayName": "Ada"}],
                    "emailAddresses": [{"value": "ada@example.com"}],
                    "phoneNumbers": [{"value": "+1"}],
                    "organizations": [{"name": "Analytical Engines"}],
                }
            ]
        }
    )
    contact_result = asyncio.run(GoogleContactsListTool(contacts).aexecute())
    assert contact_result["result"]["contacts"][0]["name"] == "Ada"
    assert contacts.calls[0]["required_scopes"] == google_scopes_for_tool("google_contacts_list")


def test_sheets_and_tasks_writes_use_their_own_descriptor_bindings() -> None:
    sheets = StubGoogleClient({"spreadsheetId": "sheet-1"})
    result = asyncio.run(GoogleSheetsWriteTool(sheets).aexecute(action="create", title="Review"))
    assert result["result"]["spreadsheet_id"] == "sheet-1"
    assert sheets.calls[0]["required_scopes"] == google_scopes_for_tool(
        "google_sheets_write", write=True
    )

    tasks = StubGoogleClient({"id": "task-1", "title": "Review"})
    result = asyncio.run(GoogleTasksWriteTool(tasks).aexecute(action="create", title="Review"))
    assert result["result"]["task_id"] == "task-1"
    assert tasks.calls[0]["required_scopes"] == google_scopes_for_tool(
        "google_tasks_write", write=True
    )


def test_missing_authorization_returns_reconnect_hint() -> None:
    client = StubGoogleClient(GoogleWorkspaceAuthError("missing required scope"))
    result = asyncio.run(GoogleDriveSearchTool(client).aexecute())
    assert result["error_type"] == "authorization"
    assert "/login google --services workspace-files" in result["hint"]
