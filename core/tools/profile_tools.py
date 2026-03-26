"""User Profile Tools — LLM-callable tools for Tier 0.5 user profile.

Tools for viewing, updating, and learning from user interactions:
- ProfileShowTool: Display current user profile
- ProfileUpdateTool: Update profile fields (role, expertise, etc.)
- ProfilePreferenceTool: Get/set specific preference
- ProfileLearnTool: Save learned pattern from interaction
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from core.memory.user_profile import FileBasedUserProfile

log = logging.getLogger(__name__)

# Thread-safe user profile via contextvars
_user_profile_ctx: ContextVar[FileBasedUserProfile | None] = ContextVar(
    "user_profile_tools", default=None
)


def set_user_profile(profile: FileBasedUserProfile | None) -> None:
    """Set the context-local user profile for profile tools."""
    _user_profile_ctx.set(profile)


def get_user_profile() -> FileBasedUserProfile | None:
    """Get the context-local user profile."""
    return _user_profile_ctx.get()


class ProfileShowTool:
    """Display current user profile."""

    @property
    def name(self) -> str:
        return "profile_show"

    @property
    def description(self) -> str:
        return (
            "Display the current user profile including role, expertise, "
            "preferences, and learned patterns."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        profile = _user_profile_ctx.get()
        if profile is None:
            return {"error": "User profile not configured"}

        data = profile.load_profile()
        patterns = profile.get_learned_patterns()

        result: dict[str, Any] = {
            "profile": data,
            "learned_patterns_count": len(patterns),
            "recent_patterns": patterns[:5],
            "exists": profile.exists(),
        }

        # Include career identity if available
        career = profile.load_career()
        if career:
            result["career"] = career

        return {"result": result}


class ProfileUpdateTool:
    """Update user profile fields."""

    @property
    def name(self) -> str:
        return "profile_update"

    @property
    def description(self) -> str:
        return (
            "Update user profile fields like role, expertise, name, team, or bio. "
            "Only provided fields are updated; others are preserved."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "description": "User's role (e.g. 'AI Engineer', 'Data Scientist')",
                },
                "expertise": {
                    "type": "string",
                    "description": "User's expertise areas (e.g. 'ML, NLP, Game Analytics')",
                },
                "name": {
                    "type": "string",
                    "description": "User's name",
                },
                "team": {
                    "type": "string",
                    "description": "User's team or department",
                },
                "bio": {
                    "type": "string",
                    "description": "Free-form bio or background text",
                },
            },
            "required": [],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        profile = _user_profile_ctx.get()
        if profile is None:
            return {"error": "User profile not configured"}

        # Merge with existing
        existing = profile.load_profile()
        for key in ("role", "expertise", "name", "team", "bio"):
            if kwargs.get(key):
                existing[key] = kwargs[key]

        success = profile.save_profile(existing)
        return {
            "result": {
                "updated": success,
                "fields": [k for k in ("role", "expertise", "name", "team", "bio") if k in kwargs],
            }
        }


class ProfilePreferenceTool:
    """Get or set a specific preference."""

    @property
    def name(self) -> str:
        return "profile_preference"

    @property
    def description(self) -> str:
        return (
            "Get or set a user preference. "
            "Provide only 'key' to read, provide 'key' and 'value' to write."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Preference key (e.g. 'language', 'output_format')",
                },
                "value": {
                    "type": "string",
                    "description": "Value to set (omit to read current value)",
                },
            },
            "required": ["key"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        profile = _user_profile_ctx.get()
        if profile is None:
            return {"error": "User profile not configured"}

        key: str = kwargs["key"]
        value = kwargs.get("value")

        if value is not None:
            success = profile.set_preference(key, value)
            return {
                "result": {
                    "action": "set",
                    "key": key,
                    "value": value,
                    "success": success,
                }
            }
        else:
            current = profile.get_preference(key)
            return {
                "result": {
                    "action": "get",
                    "key": key,
                    "value": current,
                }
            }


class ProfileLearnTool:
    """Save a learned pattern from interaction."""

    @property
    def name(self) -> str:
        return "profile_learn"

    @property
    def description(self) -> str:
        return (
            "Save a learned pattern or insight from the current interaction. "
            "Use when you discover a recurring user preference, workflow pattern, "
            "or domain interest that should be remembered for future sessions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The pattern or insight to remember",
                },
                "category": {
                    "type": "string",
                    "enum": ["general", "domain", "workflow", "preference", "tool_usage"],
                    "description": "Category of the pattern (default: general)",
                },
            },
            "required": ["pattern"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        profile = _user_profile_ctx.get()
        if profile is None:
            return {"error": "User profile not configured"}

        pattern: str = kwargs["pattern"]
        category: str = kwargs.get("category", "general")

        success = profile.add_learned_pattern(pattern, category)
        return {
            "result": {
                "saved": success,
                "pattern": pattern[:100],
                "category": category,
                "deduplicated": not success,
            }
        }
