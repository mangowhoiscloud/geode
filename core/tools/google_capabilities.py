"""Immutable Google Workspace service capability metadata.

API service IDs follow https://developers.google.com/workspace/guides/enable-apis.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class GoogleServiceDescriptor:
    """One least-privilege OAuth bundle and its static prerequisites.

    ``required_api_services`` holds Google Service Usage IDs accepted by
    ``gcloud services enable``; it is not an API host allowlist or runtime probe.
    """

    name: str
    scopes: tuple[str, ...]
    description: str
    risk: str
    required_api_services: tuple[str, ...] = ()
    implies: tuple[str, ...] = ()
    recommended: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", tuple(self.scopes))
        object.__setattr__(self, "required_api_services", tuple(self.required_api_services))
        object.__setattr__(self, "implies", tuple(self.implies))


@dataclass(frozen=True, slots=True)
class GoogleToolBinding:
    """Static Google auth and delegated-handler metadata for one tool.

    Calendar tools remain composite (Google direct, MCP, or Apple). Their
    service names describe only the direct Google adapter's accepted scopes;
    they are not a runtime availability gate.
    """

    name: str
    read_services: tuple[str, ...] = ()
    write_services: tuple[str, ...] = ()
    handler_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "read_services", tuple(self.read_services))
        object.__setattr__(self, "write_services", tuple(self.write_services))


def _descriptor_catalog(
    entries: tuple[GoogleServiceDescriptor, ...],
) -> Mapping[str, GoogleServiceDescriptor]:
    catalog: dict[str, GoogleServiceDescriptor] = {}
    for descriptor in entries:
        if descriptor.name in catalog:
            raise ValueError(f"duplicate Google service descriptor: {descriptor.name}")
        catalog[descriptor.name] = descriptor
    for descriptor in catalog.values():
        invalid = set(descriptor.implies) - catalog.keys()
        if descriptor.name in descriptor.implies or invalid:
            raise ValueError(f"invalid Google service implications: {descriptor.name}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"cyclic Google service implications: {name}")
        if name in visited:
            return
        visiting.add(name)
        for implied in catalog[name].implies:
            visit(implied)
        visiting.remove(name)
        visited.add(name)

    for name in catalog:
        visit(name)
    return MappingProxyType(catalog)


_GOOGLE_SERVICE_DESCRIPTOR_VALUES = (
    GoogleServiceDescriptor(
        "gmail-send",
        ("https://www.googleapis.com/auth/gmail.send",),
        "Send mail without reading the mailbox",
        "sensitive",
        ("gmail.googleapis.com",),
        recommended=True,
    ),
    GoogleServiceDescriptor(
        "gmail-read",
        ("https://www.googleapis.com/auth/gmail.readonly",),
        "Search and read Gmail messages",
        "restricted",
        ("gmail.googleapis.com",),
    ),
    GoogleServiceDescriptor(
        "calendar-read",
        ("https://www.googleapis.com/auth/calendar.events.owned.readonly",),
        "Read events on calendars owned by the account",
        "sensitive",
        ("calendar-json.googleapis.com",),
        recommended=True,
    ),
    GoogleServiceDescriptor(
        "calendar-write",
        ("https://www.googleapis.com/auth/calendar.events.owned",),
        "Read and edit events on calendars owned by the account",
        "sensitive",
        ("calendar-json.googleapis.com",),
        implies=("calendar-read",),
    ),
    GoogleServiceDescriptor(
        "workspace-files",
        ("https://www.googleapis.com/auth/drive.file",),
        "Use Drive, Docs, and Sheets files created or explicitly opened by GEODE",
        "non-sensitive",
        (
            "drive.googleapis.com",
            "docs.googleapis.com",
            "sheets.googleapis.com",
        ),
        recommended=True,
    ),
    GoogleServiceDescriptor(
        "tasks-read",
        ("https://www.googleapis.com/auth/tasks.readonly",),
        "Read Google Tasks",
        "sensitive",
        ("tasks.googleapis.com",),
    ),
    GoogleServiceDescriptor(
        "tasks-write",
        ("https://www.googleapis.com/auth/tasks",),
        "Read and edit Google Tasks",
        "sensitive",
        ("tasks.googleapis.com",),
        implies=("tasks-read",),
    ),
    GoogleServiceDescriptor(
        "contacts-read",
        ("https://www.googleapis.com/auth/contacts.readonly",),
        "Read Google Contacts through the People API",
        "sensitive",
        ("people.googleapis.com",),
    ),
)
GOOGLE_SERVICE_DESCRIPTORS: Mapping[str, GoogleServiceDescriptor] = _descriptor_catalog(
    _GOOGLE_SERVICE_DESCRIPTOR_VALUES
)


def _tool_binding_catalog(
    entries: tuple[GoogleToolBinding, ...],
) -> Mapping[str, GoogleToolBinding]:
    catalog: dict[str, GoogleToolBinding] = {}
    for binding in entries:
        if not binding.name or binding.name in catalog:
            raise ValueError(f"duplicate or empty Google tool binding: {binding.name}")
        services = (*binding.read_services, *binding.write_services)
        if not services or set(services) - GOOGLE_SERVICE_DESCRIPTORS.keys():
            raise ValueError(f"invalid Google services for tool: {binding.name}")
        catalog[binding.name] = binding
    return MappingProxyType(catalog)


_GOOGLE_TOOL_BINDING_VALUES = (
    GoogleToolBinding("gmail_search", ("gmail-read",), handler_class="GmailSearchTool"),
    GoogleToolBinding("gmail_send", write_services=("gmail-send",), handler_class="GmailSendTool"),
    GoogleToolBinding(
        "google_drive_search", ("workspace-files",), handler_class="GoogleDriveSearchTool"
    ),
    GoogleToolBinding(
        "google_drive_create",
        write_services=("workspace-files",),
        handler_class="GoogleDriveCreateTool",
    ),
    GoogleToolBinding("google_docs_read", ("workspace-files",), handler_class="GoogleDocsReadTool"),
    GoogleToolBinding(
        "google_docs_write",
        write_services=("workspace-files",),
        handler_class="GoogleDocsWriteTool",
    ),
    GoogleToolBinding(
        "google_sheets_read", ("workspace-files",), handler_class="GoogleSheetsReadTool"
    ),
    GoogleToolBinding(
        "google_sheets_write",
        write_services=("workspace-files",),
        handler_class="GoogleSheetsWriteTool",
    ),
    GoogleToolBinding(
        "google_tasks_list", ("tasks-read", "tasks-write"), handler_class="GoogleTasksListTool"
    ),
    GoogleToolBinding(
        "google_tasks_write",
        write_services=("tasks-write",),
        handler_class="GoogleTasksWriteTool",
    ),
    GoogleToolBinding(
        "google_contacts_list", ("contacts-read",), handler_class="GoogleContactsListTool"
    ),
    GoogleToolBinding("calendar_list_events", ("calendar-read", "calendar-write")),
    GoogleToolBinding("calendar_create_event", write_services=("calendar-write",)),
    GoogleToolBinding(
        "calendar_sync_scheduler",
        ("calendar-read", "calendar-write"),
        ("calendar-write",),
    ),
)
GOOGLE_TOOL_BINDINGS: Mapping[str, GoogleToolBinding] = _tool_binding_catalog(
    _GOOGLE_TOOL_BINDING_VALUES
)


def _services_for_binding(binding: GoogleToolBinding) -> tuple[GoogleServiceDescriptor, ...]:
    names = dict.fromkeys((*binding.read_services, *binding.write_services))
    return tuple(GOOGLE_SERVICE_DESCRIPTORS[name] for name in names)


GOOGLE_TOOL_SERVICES: Mapping[str, tuple[GoogleServiceDescriptor, ...]] = MappingProxyType(
    {name: _services_for_binding(binding) for name, binding in GOOGLE_TOOL_BINDINGS.items()}
)
GOOGLE_WRITE_TOOLS = frozenset(
    name for name, binding in GOOGLE_TOOL_BINDINGS.items() if binding.write_services
)
GOOGLE_READ_TOOLS = frozenset(
    name
    for name, binding in GOOGLE_TOOL_BINDINGS.items()
    if binding.read_services and not binding.write_services
)
GOOGLE_PERSONAL_DATA_TOOLS = GOOGLE_READ_TOOLS | GOOGLE_WRITE_TOOLS


def google_scopes_for_tool(tool_name: str, *, write: bool = False) -> tuple[str, ...]:
    """Return accepted OAuth scopes for one direct Google operation."""
    binding = GOOGLE_TOOL_BINDINGS[tool_name]
    service_names = binding.write_services if write else binding.read_services
    if not service_names:
        raise ValueError(
            f"Google tool does not support {'write' if write else 'read'}: {tool_name}"
        )
    return tuple(
        dict.fromkeys(
            scope
            for service_name in service_names
            for scope in GOOGLE_SERVICE_DESCRIPTORS[service_name].scopes
        )
    )
