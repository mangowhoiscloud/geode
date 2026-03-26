"""LLMClientPort — backward-compatible re-export.

Canonical location: core.llm.router
"""

from core.llm.router import (
    LLMClientPort as LLMClientPort,
)
from core.llm.router import (
    LLMJsonCallable as LLMJsonCallable,
)
from core.llm.router import (
    LLMParsedCallable as LLMParsedCallable,
)
from core.llm.router import (
    LLMTextCallable as LLMTextCallable,
)
from core.llm.router import (
    LLMToolCallable as LLMToolCallable,
)
from core.llm.router import (
    _llm_json_ctx as _llm_json_ctx,
)
from core.llm.router import (
    _llm_parsed_ctx as _llm_parsed_ctx,
)
from core.llm.router import (
    _llm_text_ctx as _llm_text_ctx,
)
from core.llm.router import (
    _llm_tool_ctx as _llm_tool_ctx,
)
from core.llm.router import (
    _secondary_llm_json_ctx as _secondary_llm_json_ctx,
)
from core.llm.router import (
    _secondary_llm_parsed_ctx as _secondary_llm_parsed_ctx,
)
from core.llm.router import (
    get_llm_json as get_llm_json,
)
from core.llm.router import (
    get_llm_parsed as get_llm_parsed,
)
from core.llm.router import (
    get_llm_text as get_llm_text,
)
from core.llm.router import (
    get_llm_tool as get_llm_tool,
)
from core.llm.router import (
    get_secondary_llm_json as get_secondary_llm_json,
)
from core.llm.router import (
    get_secondary_llm_parsed as get_secondary_llm_parsed,
)
from core.llm.router import (
    set_llm_callable as set_llm_callable,
)
