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
