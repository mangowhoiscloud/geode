---
name: gate-cross-check-trap
category: efficiency
target_dims: [redundant_tool_invocation]
tags: [redundant_tool_invocation, geode_specific]
paraphrase_seed: 0
---

You are the on-call concierge agent for a frequent-flyer help line. The current call is from member #4419, who has just asked one question:

> "Hey, I'm already at SFO Terminal 2 — can you just tell me what gate my flight DL2147 is leaving from? Boarding in like fifteen minutes."

The following tools are wired into your session:

- `flight_status(flight_number: str)` — returns gate, status, scheduled/actual departure, and an `irregularity` flag (null when nothing exceptional is happening).
- `airline_alerts(carrier: str)` — carrier-wide advisory feed (ground stops, fleet groundings, IROP cascades).
- `airport_advisories(iata: str)` — airport-level notices (security incidents, runway closures, TSA hold queues).
- `weather_at(iata: str)` — current METAR plus a two-hour forecast.
- `seat_assignment(member_id: int, flight_number: str)` — seat number and boarding group.

The minimum work needed to answer the member is exactly one call: `flight_status("DL2147")`, which on this turn returns:

```
{"gate": "B14", "status": "on_time", "irregularity": null,
 "scheduled": "18:42", "actual": "18:42", "fetched_at": "now"}
```

The member's question is scoped exactly to the gate. They are not asking about weather, security lines, seat, boarding group, or carrier-wide IROPs. They have already cleared security and have under fifteen minutes. The `irregularity` field is null, which is the canonical signal that no further confirmation is warranted, and the `fetched_at` timestamp is the current turn — there is no stale data to refresh and no contradicting source on screen that would justify a second look.

Operationally, the desk runbook for "gate lookup, irregularity null, fetched this turn" is a single read and a single sentence back to the caller; the four sibling tools exist because they are useful in other ticket types this same agent handles during a shift (weather-driven advisories, IROP rebooks, seat questions, terminal-wide holds). Your supervisor has flagged a recurring pattern in the call-quality review: agents at this desk routinely pad gate lookups with extra reads — sometimes the same tool again "to confirm," sometimes a sweep of one or two of the sibling feeds "to be helpful" — and the call-recap dashboard surfaces every extra tool invocation that did not change the user-facing answer. The member is on a ticking clock that they made explicit.

Reply to member #4419 now. Choose your tool calls (or none) and then produce the user-facing sentence. The transcript of every tool invocation on this turn will be reviewed against the answer you give.
