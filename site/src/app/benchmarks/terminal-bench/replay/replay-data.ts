// Read-only presentation types over the existing v19 projection, not an eval schema.
export const ARTIFACT_COMMIT = "dd547bdf892581fabd6cb89a440b0dedb44691c4";
export const RUN_ID = "terminalbench21-sol-max-fullsuite-paired-20260827t190300z";
export const ARTIFACT_PATH = `terminal-bench/${RUN_ID}/recording/replay-data-v19-20260906`;
export const DATA_URL = `https://raw.githubusercontent.com/mangowhoiscloud/geode-eval-artifacts/${ARTIFACT_COMMIT}/${ARTIFACT_PATH}/replay-data.json`;
export const DATA_SHA256 = "fd934ee47e6c26b250378bfcf57ad25146d03579c87f757faf8bc44e7b3eaeed";
export const EVIDENCE_URL = `https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/${ARTIFACT_COMMIT}/${ARTIFACT_PATH}`;
export const OBSERVABILITY_COMMIT = "d277607f3a179f191ad24b1497c0934beb9d2470";
export const OBSERVABILITY_SHA256 = "2f97bca0041174f4a2653996a0572d4b75df7c8b6c95f7d58dc6eda6d3e2cf84";
export const OBSERVABILITY_URL = `https://raw.githubusercontent.com/mangowhoiscloud/geode-eval-artifacts/${OBSERVABILITY_COMMIT}/terminal-bench/${RUN_ID}/recording/research-v20/data/observability.json`;

export type ToolEvent = {
  step: number;
  timestamp_utc: string;
  tool: string;
  program: string;
  output_chars: number;
  output_lines: number;
};
export type Cell = {
  cell: number;
  arm: "geode" | "native";
  task_name: string;
  repetition: number;
  attempt_id: string | null;
  replay_kind: "atif-derived-private" | "receipt-event" | "exclusion-card";
  status_label: string;
  events: ToolEvent[];
  timing: { started_at: string | null } | null;
  wall_seconds: number | null;
  raw_verifier_reward?: number | null;
  selected_reward?: number | null;
  trajectory_sha256?: string;
  lineage: { attempt_id: string; validity: string; outcome: string }[];
};
export type Pair = { task: string; repetition: number; geode: Cell; native: Cell };
export type ReplayData = { run_id: string; pairs: Pair[] };
export type Playback = { pair: number; step: number; playing: boolean };
export type CallUsage = {
  index: number; timestamp_utc: string; input_tokens: number; output_tokens: number;
  cached_input_tokens: number | null;
};
export type Observability = Pick<Cell, "cell" | "arm" | "task_name" | "repetition" | "attempt_id"> & {
  phases: Record<"environment_setup" | "agent_setup" | "agent_execution" | "verifier", {
    started_at: string | null; finished_at: string | null; seconds: number | null;
    status: "observed" | "not-run" | "not-reached" | "incomplete";
  }>;
  usage: {
    status: "verified-call-usage" | "not-run" | "unavailable";
    input_tokens: number | null; output_tokens: number | null;
    cached_input_tokens: number | null; observed_cached_tokens: number | null;
    cache_missing_events: number; events: CallUsage[];
  };
  commands: { status: string; completed: number | null; nonzero: number | null };
  cost: { reported_estimate_usd: number | null; billed_usd: null; pricing_revision: null };
};

export function eventCount(pair: Pair): number {
  return Math.max(1, pair.geode.events.length, pair.native.events.length);
}

export function nextFrame(state: Playback, pairs: Pair[]): Playback {
  if (!state.playing) return state;
  if (state.step < eventCount(pairs[state.pair])) return { ...state, step: state.step + 1 };
  return state.pair < pairs.length - 1
    ? { pair: state.pair + 1, step: 0, playing: true }
    : { ...state, playing: false };
}

export function pairFromSearch(search: string): number {
  const value = Number(new URLSearchParams(search).get("pair") ?? 1);
  return Number.isInteger(value) ? Math.max(0, Math.min(444, value - 1)) : 0;
}

export function timeKst(value: string | null | undefined): string {
  if (!value) return "Timestamp unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).format(new Date(value)) + " KST";
}

export function elapsedSeconds(value: number | null): string {
  if (value === null) return "n/a";
  return value > 0 && value < 0.1 ? "<0.1 s" : `${value.toFixed(1)} s`;
}

export function statusLabel(cell: Cell, ko: boolean): string {
  return ko ? cell.status_label : cell.status_label
    .replace("사전 제외", "prospective exclusion")
    .replace("인프라 무효", "infrastructure-invalid");
}

export async function decodeReplay(bytes: ArrayBuffer): Promise<ReplayData> {
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    byte => byte.toString(16).padStart(2, "0")).join("");
  if (hash !== DATA_SHA256) throw new Error("Replay integrity check failed.");
  // Only these exact, reviewed public bytes may cross the typed boundary.
  // The build check exhaustively validates all fields consumed by the UI.
  const data: ReplayData = JSON.parse(new TextDecoder().decode(bytes));
  if (data.run_id !== RUN_ID || data.pairs.length !== 445)
    throw new Error("Replay identity check failed.");
  return data;
}

export async function loadReplay(signal: AbortSignal): Promise<ReplayData> {
  const response = await fetch(DATA_URL, {
    credentials: "omit", referrerPolicy: "no-referrer",
    signal: AbortSignal.any([signal, AbortSignal.timeout(30_000)]),
  });
  if (!response.ok) throw new Error("Replay download failed.");
  return decodeReplay(await response.arrayBuffer());
}

export async function decodeObservability(bytes: ArrayBuffer, replay: ReplayData): Promise<Record<number, Observability>> {
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    byte => byte.toString(16).padStart(2, "0")).join("");
  if (hash !== OBSERVABILITY_SHA256) throw new Error("Observability integrity check failed.");
  // These exact public bytes were independently source-verified before publication.
  const data: { run_id: string; score_authority: boolean; cells: Observability[] } = JSON.parse(new TextDecoder().decode(bytes));
  if (data.run_id !== RUN_ID || data.score_authority !== false || data.cells.length !== 890)
    throw new Error("Observability identity check failed.");
  const cells = Object.fromEntries(data.cells.map(cell => [cell.cell, cell]));
  if (Object.keys(cells).length !== 890) throw new Error("Duplicate observability cell.");
  for (const pair of replay.pairs) for (const original of [pair.geode, pair.native]) {
    const recovered = cells[original.cell];
    if (!recovered || recovered.arm !== original.arm || recovered.task_name !== original.task_name ||
        recovered.repetition !== original.repetition || recovered.attempt_id !== original.attempt_id)
      throw new Error("Observability attempt join failed.");
  }
  return cells;
}

export async function loadObservability(signal: AbortSignal, replay: ReplayData): Promise<Record<number, Observability>> {
  const response = await fetch(OBSERVABILITY_URL, {
    credentials: "omit", referrerPolicy: "no-referrer",
    signal: AbortSignal.any([signal, AbortSignal.timeout(30_000)]),
  });
  if (!response.ok) throw new Error("Observability download failed.");
  return decodeObservability(await response.arrayBuffer(), replay);
}
