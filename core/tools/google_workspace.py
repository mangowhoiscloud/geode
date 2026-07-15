"""Google Workspace tools backed by /login google OAuth credentials."""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote

from core.mcp.google_workspace_client import (
    GoogleWorkspaceAuthError,
    GoogleWorkspaceClient,
    GoogleWorkspaceError,
    get_google_workspace_client,
)
from core.tools.base import tool_error

GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
TASKS_READ_SCOPE = "https://www.googleapis.com/auth/tasks.readonly"
TASKS_WRITE_SCOPE = "https://www.googleapis.com/auth/tasks"
CONTACTS_READ_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
_TASKS_READ_SCOPES = (TASKS_READ_SCOPE, TASKS_WRITE_SCOPE)


class _GoogleToolBase:
    def __init__(self, client: GoogleWorkspaceClient | None = None) -> None:
        self._google = client or get_google_workspace_client()

    @staticmethod
    def _failure(exc: Exception, service_bundle: str) -> dict[str, Any]:
        if isinstance(exc, (KeyError, TypeError, ValueError)):
            return tool_error(
                str(exc),
                error_type="validation",
                recoverable=False,
            )
        if isinstance(exc, GoogleWorkspaceAuthError):
            return tool_error(
                str(exc),
                error_type="authorization",
                recoverable=False,
                hint=f"Run /login google --services {service_bundle}.",
            )
        if isinstance(exc, GoogleWorkspaceError):
            return tool_error(
                str(exc),
                error_type="connection",
                hint="Check Google API enablement, account policy, and retry.",
            )
        return tool_error(
            f"Google Workspace operation failed: {exc}",
            error_type="internal",
        )


class GmailSearchTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "gmail_search"

    @property
    def description(self) -> str:
        return (
            "Search or fetch Gmail messages after explicit user approval. "
            "Requires the restricted gmail-read service bundle."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "message_id": {"type": "string"},
                "max_results": {"type": "integer", "default": 10},
                "include_body": {"type": "boolean", "default": False},
                "max_body_chars": {"type": "integer", "default": 12000},
            },
            "required": [],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            message_id = str(kwargs.get("message_id", "")).strip()
            include_body = bool(kwargs.get("include_body", False))
            max_body_chars = max(0, min(int(kwargs.get("max_body_chars", 12000)), 50000))
            if message_id:
                message = await self._get_message(message_id, include_body, max_body_chars)
                return {"result": {"message": message}}
            limit = max(1, min(int(kwargs.get("max_results", 10)), 20))
            payload = await self._google.request_json(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                required_scopes=(GMAIL_READ_SCOPE,),
                params={
                    "q": str(kwargs.get("query", "")),
                    "maxResults": limit,
                },
            )
            rows = [
                item
                for item in payload.get("messages", [])
                if isinstance(item, dict) and item.get("id")
            ][:limit]
            messages = await asyncio.gather(
                *(
                    self._get_message(
                        str(row["id"]),
                        include_body,
                        max_body_chars,
                    )
                    for row in rows
                )
            )
            return {
                "result": {
                    "messages": list(messages),
                    "count": len(messages),
                    "result_size_estimate": int(payload.get("resultSizeEstimate", len(messages))),
                }
            }
        except Exception as exc:
            return self._failure(exc, "gmail-read")

    async def _get_message(
        self,
        message_id: str,
        include_body: bool,
        max_body_chars: int,
    ) -> dict[str, Any]:
        safe_id = quote(message_id, safe="")
        payload = await self._google.request_json(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{safe_id}",
            required_scopes=(GMAIL_READ_SCOPE,),
            params={
                "format": "full" if include_body else "metadata",
                "metadataHeaders": ["Subject", "From", "To", "Date"],
            },
        )
        headers = _gmail_headers(payload.get("payload"))
        result: dict[str, Any] = {
            "id": str(payload.get("id", "")),
            "thread_id": str(payload.get("threadId", "")),
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "snippet": str(payload.get("snippet", "")),
            "label_ids": [str(v) for v in payload.get("labelIds", [])],
        }
        if include_body:
            body = _gmail_body(payload.get("payload"))
            result["body"] = body[:max_body_chars]
            result["body_truncated"] = len(body) > max_body_chars
        return result


class GmailSendTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "gmail_send"

    @property
    def description(self) -> str:
        return "Send an email through Gmail. Always requires user approval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "cc": {"type": "string"},
                "bcc": {"type": "string"},
                "reply_to_message_id": {"type": "string"},
                "thread_id": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            recipient = str(kwargs["to"])
            subject = str(kwargs["subject"])
            cc = str(kwargs.get("cc", ""))
            bcc = str(kwargs.get("bcc", ""))
            _reject_header_newlines(recipient, subject, cc, bcc)
            message = EmailMessage()
            message["To"] = recipient
            message["Subject"] = subject
            if cc:
                message["Cc"] = cc
            if bcc:
                message["Bcc"] = bcc
            reply_to_id = str(kwargs.get("reply_to_message_id", ""))
            if reply_to_id:
                _reject_header_newlines(reply_to_id)
                message["In-Reply-To"] = reply_to_id
                message["References"] = reply_to_id
            message.set_content(str(kwargs["body"]))
            body: dict[str, Any] = {
                "raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
            }
            thread_id = str(kwargs.get("thread_id", "")).strip()
            if thread_id:
                body["threadId"] = thread_id
            payload = await self._google.request_json(
                "POST",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                required_scopes=(GMAIL_SEND_SCOPE,),
                json_body=body,
            )
            return {
                "result": {
                    "sent": True,
                    "message_id": str(payload.get("id", "")),
                    "thread_id": str(payload.get("threadId", "")),
                    "to": recipient,
                    "subject": subject,
                }
            }
        except Exception as exc:
            return self._failure(exc, "gmail-send")


class GoogleDriveSearchTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_drive_search"

    @property
    def description(self) -> str:
        return (
            "Search Drive files visible to GEODE through drive.file. "
            "This does not grant whole-Drive access."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": [],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            query = str(kwargs.get("query", "")).strip()
            q = "trashed = false"
            if query:
                escaped = query.replace("\\", "\\\\").replace("'", "\\'")
                q += f" and name contains '{escaped}'"
            payload = await self._google.request_json(
                "GET",
                "https://www.googleapis.com/drive/v3/files",
                required_scopes=(DRIVE_FILE_SCOPE,),
                params={
                    "q": q,
                    "pageSize": max(1, min(int(kwargs.get("max_results", 20)), 100)),
                    "orderBy": "modifiedTime desc",
                    "fields": (
                        "files(id,name,mimeType,modifiedTime,webViewLink,size,"
                        "owners(displayName,emailAddress))"
                    ),
                },
            )
            files = [
                _drive_file_row(row) for row in payload.get("files", []) if isinstance(row, dict)
            ]
            return {"result": {"files": files, "count": len(files)}}
        except Exception as exc:
            return self._failure(exc, "workspace-files")


class GoogleDriveCreateTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_drive_create"

    @property
    def description(self) -> str:
        return "Create a text file or folder in Google Drive. Requires user approval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["text", "folder"]},
                "name": {"type": "string"},
                "content": {"type": "string"},
                "parent_id": {"type": "string"},
            },
            "required": ["kind", "name"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            kind = str(kwargs["kind"])
            name = str(kwargs["name"]).strip()
            if not name:
                raise ValueError("name must not be empty")
            metadata: dict[str, Any] = {"name": name}
            parent_id = str(kwargs.get("parent_id", "")).strip()
            if parent_id:
                metadata["parents"] = [parent_id]
            if kind == "folder":
                metadata["mimeType"] = "application/vnd.google-apps.folder"
                payload = await self._google.request_json(
                    "POST",
                    "https://www.googleapis.com/drive/v3/files",
                    required_scopes=(DRIVE_FILE_SCOPE,),
                    params={"fields": "id,name,mimeType,webViewLink"},
                    json_body=metadata,
                )
            elif kind == "text":
                payload = await self._upload_text(metadata, str(kwargs.get("content", "")))
            else:
                raise ValueError(f"Unsupported Drive create kind: {kind}")
            return {"result": {"created": True, "file": _drive_file_row(payload)}}
        except Exception as exc:
            return self._failure(exc, "workspace-files")

    async def _upload_text(self, metadata: dict[str, Any], content: str) -> dict[str, Any]:
        boundary = "geode-" + secrets.token_hex(16)
        raw = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata, ensure_ascii=False)}\r\n"
            f"--{boundary}\r\n"
            "Content-Type: text/plain; charset=UTF-8\r\n\r\n"
            f"{content}\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        response = await self._google.request(
            "POST",
            "https://www.googleapis.com/upload/drive/v3/files",
            required_scopes=(DRIVE_FILE_SCOPE,),
            params={"uploadType": "multipart", "fields": "id,name,mimeType,webViewLink,size"},
            content=raw,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        )
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


class GoogleDocsReadTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_docs_read"

    @property
    def description(self) -> str:
        return "Read a Google Doc visible through the workspace-files bundle."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "max_chars": {"type": "integer", "default": 30000},
            },
            "required": ["document_id"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            document_id = quote(str(kwargs["document_id"]), safe="")
            payload = await self._google.request_json(
                "GET",
                f"https://docs.googleapis.com/v1/documents/{document_id}",
                required_scopes=(DRIVE_FILE_SCOPE,),
            )
            text = _document_text(payload)
            max_chars = max(0, min(int(kwargs.get("max_chars", 30000)), 100000))
            return {
                "result": {
                    "document_id": str(payload.get("documentId", "")),
                    "title": str(payload.get("title", "")),
                    "text": text[:max_chars],
                    "truncated": len(text) > max_chars,
                }
            }
        except Exception as exc:
            return self._failure(exc, "workspace-files")


class GoogleDocsWriteTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_docs_write"

    @property
    def description(self) -> str:
        return "Create a Google Doc or append text to one. Requires user approval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "append"]},
                "document_id": {"type": "string"},
                "title": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["action", "text"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            action = str(kwargs["action"])
            text = str(kwargs["text"])
            if action == "create":
                title = str(kwargs.get("title", "")).strip()
                if not title:
                    raise ValueError("title is required for create")
                created = await self._google.request_json(
                    "POST",
                    "https://docs.googleapis.com/v1/documents",
                    required_scopes=(DRIVE_FILE_SCOPE,),
                    json_body={"title": title},
                )
                document_id = str(created.get("documentId", ""))
                index = 1
            elif action == "append":
                document_id = str(kwargs.get("document_id", "")).strip()
                if not document_id:
                    raise ValueError("document_id is required for append")
                current = await self._google.request_json(
                    "GET",
                    f"https://docs.googleapis.com/v1/documents/{quote(document_id, safe='')}",
                    required_scopes=(DRIVE_FILE_SCOPE,),
                )
                index = max(1, _document_end_index(current) - 1)
            else:
                raise ValueError(f"Unsupported Docs action: {action}")
            await self._google.request_json(
                "POST",
                (
                    "https://docs.googleapis.com/v1/documents/"
                    f"{quote(document_id, safe='')}:batchUpdate"
                ),
                required_scopes=(DRIVE_FILE_SCOPE,),
                json_body={
                    "requests": [{"insertText": {"location": {"index": index}, "text": text}}]
                },
            )
            return {
                "result": {
                    "updated": True,
                    "action": action,
                    "document_id": document_id,
                    "inserted_chars": len(text),
                }
            }
        except Exception as exc:
            return self._failure(exc, "workspace-files")


class GoogleSheetsReadTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_sheets_read"

    @property
    def description(self) -> str:
        return "Read a bounded range from a Google Sheet visible to GEODE."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range": {"type": "string"},
                "major_dimension": {"type": "string", "enum": ["ROWS", "COLUMNS"]},
            },
            "required": ["spreadsheet_id", "range"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            spreadsheet_id = quote(str(kwargs["spreadsheet_id"]), safe="")
            cell_range = quote(str(kwargs["range"]), safe="")
            payload = await self._google.request_json(
                "GET",
                (
                    "https://sheets.googleapis.com/v4/spreadsheets/"
                    f"{spreadsheet_id}/values/{cell_range}"
                ),
                required_scopes=(DRIVE_FILE_SCOPE,),
                params={
                    "majorDimension": str(kwargs.get("major_dimension", "ROWS")),
                },
            )
            values = payload.get("values", [])
            return {
                "result": {
                    "range": str(payload.get("range", kwargs["range"])),
                    "major_dimension": str(payload.get("majorDimension", "ROWS")),
                    "values": values,
                    "row_count": len(values) if isinstance(values, list) else 0,
                }
            }
        except Exception as exc:
            return self._failure(exc, "workspace-files")


class GoogleSheetsWriteTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_sheets_write"

    @property
    def description(self) -> str:
        return "Create a spreadsheet, update a range, or append rows. Requires user approval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update", "append"]},
                "spreadsheet_id": {"type": "string"},
                "title": {"type": "string"},
                "range": {"type": "string"},
                "values": {"type": "array", "items": {"type": "array"}},
            },
            "required": ["action"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            action = str(kwargs["action"])
            values = kwargs.get("values", [])
            if action == "create":
                title = str(kwargs.get("title", "")).strip()
                if not title:
                    raise ValueError("title is required for create")
                created = await self._google.request_json(
                    "POST",
                    "https://sheets.googleapis.com/v4/spreadsheets",
                    required_scopes=(DRIVE_FILE_SCOPE,),
                    json_body={"properties": {"title": title}},
                )
                spreadsheet_id = str(created.get("spreadsheetId", ""))
                if values:
                    await self._write_values(
                        spreadsheet_id,
                        str(kwargs.get("range", "Sheet1!A1")),
                        values,
                        append=False,
                    )
            elif action in ("update", "append"):
                spreadsheet_id = str(kwargs.get("spreadsheet_id", "")).strip()
                cell_range = str(kwargs.get("range", "")).strip()
                if not spreadsheet_id or not cell_range or not isinstance(values, list):
                    raise ValueError("spreadsheet_id, range, and values are required")
                await self._write_values(
                    spreadsheet_id,
                    cell_range,
                    values,
                    append=action == "append",
                )
            else:
                raise ValueError(f"Unsupported Sheets action: {action}")
            return {
                "result": {
                    "updated": True,
                    "action": action,
                    "spreadsheet_id": spreadsheet_id,
                    "rows": len(values) if isinstance(values, list) else 0,
                }
            }
        except Exception as exc:
            return self._failure(exc, "workspace-files")

    async def _write_values(
        self,
        spreadsheet_id: str,
        cell_range: str,
        values: list[Any],
        *,
        append: bool,
    ) -> None:
        method = "append" if append else ""
        suffix = f":{method}" if method else ""
        await self._google.request_json(
            "POST" if append else "PUT",
            (
                "https://sheets.googleapis.com/v4/spreadsheets/"
                f"{quote(spreadsheet_id, safe='')}/values/{quote(cell_range, safe='')}{suffix}"
            ),
            required_scopes=(DRIVE_FILE_SCOPE,),
            params={"valueInputOption": "USER_ENTERED"},
            json_body={"range": cell_range, "majorDimension": "ROWS", "values": values},
        )


class GoogleTasksListTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_tasks_list"

    @property
    def description(self) -> str:
        return "List Google Tasks after explicit user approval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tasklist_id": {"type": "string", "default": "@default"},
                "max_results": {"type": "integer", "default": 50},
                "show_completed": {"type": "boolean", "default": False},
            },
            "required": [],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            tasklist_id = quote(str(kwargs.get("tasklist_id", "@default")), safe="")
            payload = await self._google.request_json(
                "GET",
                f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks",
                required_scopes=_TASKS_READ_SCOPES,
                any_scope=True,
                params={
                    "maxResults": max(1, min(int(kwargs.get("max_results", 50)), 100)),
                    "showCompleted": str(bool(kwargs.get("show_completed", False))).lower(),
                    "showHidden": "false",
                },
            )
            tasks = [
                {
                    "id": str(item.get("id", "")),
                    "title": str(item.get("title", "")),
                    "notes": str(item.get("notes", "")),
                    "status": str(item.get("status", "")),
                    "due": str(item.get("due", "")),
                    "completed": str(item.get("completed", "")),
                    "web_view_link": str(item.get("webViewLink", "")),
                }
                for item in payload.get("items", [])
                if isinstance(item, dict)
            ]
            return {"result": {"tasks": tasks, "count": len(tasks)}}
        except Exception as exc:
            return self._failure(exc, "tasks-read")


class GoogleTasksWriteTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_tasks_write"

    @property
    def description(self) -> str:
        return "Create, complete, or delete a Google Task. Requires user approval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "complete", "delete"]},
                "tasklist_id": {"type": "string", "default": "@default"},
                "task_id": {"type": "string"},
                "title": {"type": "string"},
                "notes": {"type": "string"},
                "due": {"type": "string"},
            },
            "required": ["action"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            action = str(kwargs["action"])
            tasklist = quote(str(kwargs.get("tasklist_id", "@default")), safe="")
            base = f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist}/tasks"
            if action == "create":
                title = str(kwargs.get("title", "")).strip()
                if not title:
                    raise ValueError("title is required for create")
                body: dict[str, Any] = {"title": title}
                for field in ("notes", "due"):
                    value = str(kwargs.get(field, "")).strip()
                    if value:
                        body[field] = value
                payload = await self._google.request_json(
                    "POST",
                    base,
                    required_scopes=(TASKS_WRITE_SCOPE,),
                    json_body=body,
                )
            else:
                task_id = str(kwargs.get("task_id", "")).strip()
                if not task_id:
                    raise ValueError(f"task_id is required for {action}")
                url = f"{base}/{quote(task_id, safe='')}"
                if action == "complete":
                    payload = await self._google.request_json(
                        "PATCH",
                        url,
                        required_scopes=(TASKS_WRITE_SCOPE,),
                        json_body={"status": "completed"},
                    )
                elif action == "delete":
                    payload = await self._google.request_json(
                        "DELETE",
                        url,
                        required_scopes=(TASKS_WRITE_SCOPE,),
                    )
                else:
                    raise ValueError(f"Unsupported Tasks action: {action}")
            return {
                "result": {
                    "updated": True,
                    "action": action,
                    "task_id": str(payload.get("id", kwargs.get("task_id", ""))),
                    "title": str(payload.get("title", kwargs.get("title", ""))),
                    "status": str(payload.get("status", "")),
                }
            }
        except Exception as exc:
            return self._failure(exc, "tasks-write")


class GoogleContactsListTool(_GoogleToolBase):
    @property
    def name(self) -> str:
        return "google_contacts_list"

    @property
    def description(self) -> str:
        return "List Google Contacts through the People API after user approval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 100},
                "sort_order": {
                    "type": "string",
                    "enum": [
                        "LAST_MODIFIED_ASCENDING",
                        "LAST_MODIFIED_DESCENDING",
                        "FIRST_NAME_ASCENDING",
                        "LAST_NAME_ASCENDING",
                    ],
                    "default": "LAST_MODIFIED_DESCENDING",
                },
            },
            "required": [],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            payload = await self._google.request_json(
                "GET",
                "https://people.googleapis.com/v1/people/me/connections",
                required_scopes=(CONTACTS_READ_SCOPE,),
                params={
                    "personFields": "names,emailAddresses,phoneNumbers,organizations",
                    "pageSize": max(1, min(int(kwargs.get("max_results", 100)), 1000)),
                    "sortOrder": str(kwargs.get("sort_order", "LAST_MODIFIED_DESCENDING")),
                },
            )
            contacts = [
                _contact_row(row) for row in payload.get("connections", []) if isinstance(row, dict)
            ]
            return {"result": {"contacts": contacts, "count": len(contacts)}}
        except Exception as exc:
            return self._failure(exc, "contacts-read")


def _reject_header_newlines(*values: str) -> None:
    if any("\r" in value or "\n" in value for value in values):
        raise ValueError("Email header fields must not contain line breaks")


def _gmail_headers(raw_payload: object) -> dict[str, str]:
    if not isinstance(raw_payload, dict):
        return {}
    headers: dict[str, str] = {}
    for row in raw_payload.get("headers", []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).lower()
        if name in {"subject", "from", "to", "date"}:
            headers[name] = str(row.get("value", ""))
    return headers


def _gmail_body(raw_payload: object) -> str:
    if not isinstance(raw_payload, dict):
        return ""
    mime_type = str(raw_payload.get("mimeType", ""))
    body = raw_payload.get("body")
    if mime_type == "text/plain" and isinstance(body, dict) and body.get("data"):
        encoded = str(body["data"])
        padded = encoded + "=" * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except (ValueError, UnicodeError):
            return ""
    for part in raw_payload.get("parts", []):
        text = _gmail_body(part)
        if text:
            return text
    if isinstance(body, dict) and body.get("data"):
        encoded = str(body["data"])
        padded = encoded + "=" * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except (ValueError, UnicodeError):
            return ""
    return ""


def _drive_file_row(raw: dict[str, Any]) -> dict[str, Any]:
    owners = raw.get("owners", [])
    return {
        "id": str(raw.get("id", "")),
        "name": str(raw.get("name", "")),
        "mime_type": str(raw.get("mimeType", "")),
        "modified_time": str(raw.get("modifiedTime", "")),
        "size": str(raw.get("size", "")),
        "web_view_link": str(raw.get("webViewLink", "")),
        "owners": [
            {
                "name": str(owner.get("displayName", "")),
                "email": str(owner.get("emailAddress", "")),
            }
            for owner in owners
            if isinstance(owner, dict)
        ],
    }


def _document_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    body = payload.get("body")
    if not isinstance(body, dict):
        return ""
    for structural in body.get("content", []):
        if not isinstance(structural, dict):
            continue
        paragraph = structural.get("paragraph")
        if not isinstance(paragraph, dict):
            continue
        for element in paragraph.get("elements", []):
            if not isinstance(element, dict):
                continue
            text_run = element.get("textRun")
            if isinstance(text_run, dict):
                chunks.append(str(text_run.get("content", "")))
    return "".join(chunks)


def _document_end_index(payload: dict[str, Any]) -> int:
    body = payload.get("body")
    if not isinstance(body, dict):
        return 1
    indexes = [
        int(row.get("endIndex", 1)) for row in body.get("content", []) if isinstance(row, dict)
    ]
    return max(indexes, default=1)


def _contact_row(raw: dict[str, Any]) -> dict[str, Any]:
    def values(field: str, key: str = "value") -> list[str]:
        rows = raw.get(field, [])
        return [str(row.get(key, "")) for row in rows if isinstance(row, dict) and row.get(key)]

    names = raw.get("names", [])
    display_name = next(
        (
            str(row.get("displayName", ""))
            for row in names
            if isinstance(row, dict) and row.get("displayName")
        ),
        "",
    )
    organizations = raw.get("organizations", [])
    organization = next(
        (
            str(row.get("name", ""))
            for row in organizations
            if isinstance(row, dict) and row.get("name")
        ),
        "",
    )
    return {
        "resource_name": str(raw.get("resourceName", "")),
        "name": display_name,
        "emails": values("emailAddresses"),
        "phones": values("phoneNumbers"),
        "organization": organization,
    }
