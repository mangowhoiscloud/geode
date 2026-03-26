"""OpenAIAdapter — backward-compatible re-export.

Canonical location: core.llm.providers.openai
"""

from core.llm.fallback import (
    CircuitBreaker as CircuitBreaker,
)
from core.llm.fallback import (
    retry_with_backoff_generic as retry_with_backoff_generic,
)
from core.llm.providers.openai import (
    OpenAIAdapter as OpenAIAdapter,
)
from core.llm.providers.openai import (
    _get_openai_client as _get_openai_client,
)
from core.llm.providers.openai import (
    reset_openai_client as reset_openai_client,
)
from core.llm.router import (
    ToolCallRecord as ToolCallRecord,
)
from core.llm.router import (
    ToolUseResult as ToolUseResult,
)
