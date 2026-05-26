"""Minimal probe — simplest possible codex-oauth gpt-5.5 call.

Bypass GEODE adapter; use raw OpenAI SDK so we can see exactly what
the API returns. This isolates whether the empty output[] is:
  (a) GEODE adapter bug (filtering / aggregation)
  (b) OpenAI SDK bug (streaming → final.output aggregation)
  (c) codex-oauth backend bug (gpt-5.5 returns empty output[])
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path


async def main() -> None:
    sys.path.insert(0, "/Users/mango/workspace/geode")
    from core.llm.adapters._openai_common import build_async_codex_client
    from core.llm.codex_oauth_usage import read_codex_oauth_token

    token = read_codex_oauth_token()
    if not token:
        print("[probe] no codex-oauth token", file=sys.stderr)
        sys.exit(1)

    client = build_async_codex_client(token)

    # Simplest possible call: tiny prompt, no schema, no reasoning param
    print("[probe] simplest call: minimal prompt, no schema, no reasoning")
    t0 = time.time()
    async with client.responses.stream(
        model="gpt-5.5",
        instructions="You are a helpful assistant.",
        input=[{"role": "user", "content": "Say 'hello world' and nothing else."}],
        store=False,
    ) as stream:
        seen_events: list[str] = []
        seen_items: list[dict] = []
        async for event in stream:
            etype = getattr(event, "type", "")
            seen_events.append(etype)
            if etype == "response.output_item.done":
                item = getattr(event, "item", None)
                if item is not None:
                    seen_items.append(
                        {
                            "type": getattr(item, "type", "?"),
                            "id": getattr(item, "id", "?"),
                            "role": getattr(item, "role", None),
                            "content_preview": str(getattr(item, "content", "?"))[:300],
                        }
                    )
        final = await stream.get_final_response()
    elapsed = time.time() - t0

    print(f"[probe] elapsed={elapsed:.1f}s")
    print(f"[probe] final.status={getattr(final, 'status', '?')}")
    print(f"[probe] final.output_text={getattr(final, 'output_text', '?')!r}")
    print(f"[probe] final.output count: {len(getattr(final, 'output', []) or [])}")
    print(f"[probe] usage: input={final.usage.input_tokens} output={final.usage.output_tokens}")

    print(f"\n[probe] SSE event types ({len(seen_events)} total, unique):")
    from collections import Counter

    counter = Counter(seen_events)
    for et, n in counter.most_common():
        print(f"  {n}x {et}")

    print(f"\n[probe] response.output_item.done items ({len(seen_items)}):")
    for i, item in enumerate(seen_items):
        print(
            f"  [{i}] type={item['type']} role={item['role']} content={item['content_preview']!r}"
        )

    # Dump final.output[] structure if non-empty
    final_output = list(getattr(final, "output", []) or [])
    if final_output:
        print("\n[probe] final.output[] details:")
        for i, item in enumerate(final_output):
            print(f"  [{i}] {item}")

    # Save full event log
    out_path = (
        Path("/Users/mango/workspace/geode/.audit/probes") / f"h6_minimal_{int(time.time())}.json"
    )
    out_path.write_text(
        json.dumps(
            {
                "elapsed": elapsed,
                "status": str(getattr(final, "status", "?")),
                "output_text": getattr(final, "output_text", ""),
                "final_output_count": len(final_output),
                "usage": {
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                },
                "sse_event_counts": dict(counter),
                "sse_done_items": seen_items,
            },
            indent=2,
            default=str,
        )
    )
    print(f"\n[probe] dump: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
