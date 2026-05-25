import fs from "node:fs";
import path from "node:path";
import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Seed Generation Runs · GEODE Docs" };

// At build time, process.cwd() is the site/ directory.
// Seeds live one level up under docs/petri-bundle/seeds/ in the repo root.
const REPO_ROOT = path.join(process.cwd(), "..");
const SEEDS_DIR = path.join(REPO_ROOT, "docs", "petri-bundle", "seeds");
const RAW_BUNDLE_URL = "/petri-bundle/seeds/";

type ListingRun = {
  run_id: string;
  gen_tag: string;
  target_dim: string;
  candidates_drafted: number;
  survivors_count: number;
  evolved_count: number;
  iterations: number;
  max_iterations: number;
  usd_spent: number;
  prompt_tokens: number;
  completion_tokens: number;
  has_meta_review: boolean;
  has_supervisor_guidance: boolean;
  literature_snapshots_count: number;
  debate_transcripts_count: number;
  url: string;
};

type Listing = { kind?: string; count?: number; runs?: ListingRun[] };

type RunDetail = {
  run: ListingRun;
  state: Record<string, unknown> | null;
  survivors: Record<string, unknown> | null;
  meta: Record<string, unknown> | null;
};

function loadRuns(): RunDetail[] {
  const listingPath = path.join(SEEDS_DIR, "listing.json");
  if (!fs.existsSync(listingPath)) return [];
  let listing: Listing;
  try {
    listing = JSON.parse(fs.readFileSync(listingPath, "utf-8")) as Listing;
  } catch {
    return [];
  }
  const runs = listing.runs ?? [];
  return runs.map((run) => {
    const runDir = path.join(SEEDS_DIR, run.run_id);
    const read = (filename: string): Record<string, unknown> | null => {
      const p = path.join(runDir, filename);
      if (!fs.existsSync(p)) return null;
      try {
        return JSON.parse(fs.readFileSync(p, "utf-8")) as Record<string, unknown>;
      } catch {
        return null;
      }
    };
    return {
      run,
      state: read("state.json"),
      survivors: read("survivors.json"),
      meta: read("meta_review.json"),
    };
  });
}

function statusOf(run: ListingRun): "ok" | "partial" | "fail" {
  if (run.candidates_drafted === 0 || run.survivors_count === 0) return "fail";
  if (run.evolved_count < run.survivors_count) return "partial";
  return "ok";
}

function fmtUSD(n: number | undefined | null): string {
  return `$${(n ?? 0).toFixed(2)}`;
}

function fmtInt(n: number | undefined | null): string {
  return (n ?? 0).toLocaleString();
}

function asString(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function asNumber(v: unknown): number {
  return typeof v === "number" ? v : 0;
}

function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function asObject(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

const STATUS_LABEL_EN = { ok: "ok", partial: "partial", fail: "fail" } as const;
const STATUS_LABEL_KO = { ok: "정상", partial: "부분", fail: "실패" } as const;

function RunsTable({ runs, locale }: { runs: RunDetail[]; locale: "ko" | "en" }) {
  const headers =
    locale === "ko"
      ? ["run_id", "gen_tag", "target_dim", "상태", "draft → surv", "evolved", "iters", "비용 USD"]
      : ["run_id", "gen_tag", "target_dim", "status", "draft → surv", "evolved", "iters", "cost USD"];
  const STATUS_LABEL = locale === "ko" ? STATUS_LABEL_KO : STATUS_LABEL_EN;

  return (
    <table>
      <thead>
        <tr>
          {headers.map((h) => (
            <th key={h}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {runs.map(({ run }) => {
          const status = statusOf(run);
          return (
            <tr key={run.run_id}>
              <td>
                <a href={`#run-${run.run_id}`}>
                  <code>{run.run_id}</code>
                </a>
              </td>
              <td><code>{run.gen_tag}</code></td>
              <td><code>{run.target_dim}</code></td>
              <td>{STATUS_LABEL[status]}</td>
              <td>{run.candidates_drafted} → {run.survivors_count}</td>
              <td>{run.evolved_count}</td>
              <td>{run.iterations}</td>
              <td>{fmtUSD(run.usd_spent)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function RunDetailBlock({ detail, locale }: { detail: RunDetail; locale: "ko" | "en" }) {
  const { run, state, survivors, meta } = detail;
  const stateObj = state ?? {};
  const survivorsList = asArray(asObject(survivors).survivors);
  const evolvedList = asArray(asObject(stateObj).evolved_candidates);
  const evolvedByParent = new Map<string, string[]>();
  for (const ev of evolvedList) {
    const evObj = asObject(ev);
    const parent = asString(evObj.parent_id);
    const id = asString(evObj.id);
    if (!parent || !id) continue;
    if (!evolvedByParent.has(parent)) evolvedByParent.set(parent, []);
    evolvedByParent.get(parent)!.push(id);
  }

  const metaObj = asObject(meta ?? asObject(stateObj).meta_review);
  const sessionSummary = asString(metaObj.session_summary);
  const nextGenPriors = asArray(metaObj.next_gen_priors);
  const evolutionYield = asObject(metaObj.evolution_yield);
  const eloDist = asObject(metaObj.elo_distribution);

  const heading = locale === "ko" ? "생존 후보" : "Survivors";
  const costHeading = locale === "ko" ? "비용 집계" : "Cost rollup";
  const summaryHeading = locale === "ko" ? "메타 리뷰 요약" : "Meta-review summary";
  const priorsHeading = locale === "ko" ? "다음 세대 prior" : "Next-gen priors";
  const yieldHeading = locale === "ko" ? "진화 산출" : "Evolution yield";
  const eloHeading = locale === "ko" ? "Elo 분포" : "Elo distribution";
  const rawLinkLabel = locale === "ko" ? "raw 번들" : "raw bundle";
  const headerKo = `${run.gen_tag} · target_dim=${run.target_dim}`;

  return (
    <details id={`run-${run.run_id}`} className="my-4 border border-white/10 rounded-md">
      <summary className="cursor-pointer px-4 py-3 hover:bg-white/[0.03] select-none">
        <code className="text-[#A573E8]">{run.run_id}</code>
        <span className="ml-3 text-white/50 text-sm">{headerKo}</span>
        <a
          href={`${RAW_BUNDLE_URL}${run.run_id}/`}
          className="ml-3 text-white/40 text-xs hover:text-[#A573E8]"
        >
          [{rawLinkLabel} ↗]
        </a>
      </summary>
      <div className="px-4 py-3 border-t border-white/10">
        {survivorsList.length > 0 && (
          <>
            <h3>{heading}</h3>
            <table>
              <thead>
                <tr>
                  <th>candidate_id</th>
                  <th>elo</th>
                  <th>pilot</th>
                  <th>{locale === "ko" ? "후보 파일" : "candidate file"}</th>
                </tr>
              </thead>
              <tbody>
                {survivorsList.map((s) => {
                  const sObj = asObject(s);
                  const sid = asString(sObj.id);
                  const elo = asNumber(sObj.elo_rating);
                  const pilotObj = asObject(sObj.pilot);
                  const pilotStatus = asString(pilotObj.status) || ".";
                  const candidatePath = asString(sObj.path);
                  const filename = candidatePath.split("/").pop() ?? "";
                  const fileHref = filename
                    ? `${RAW_BUNDLE_URL}${run.run_id}/candidates/${filename}`
                    : undefined;
                  const evolved = evolvedByParent.get(sid) ?? [];
                  const detailHref = `/docs/petri/seeds/${run.run_id}/${sid}/`;
                  return (
                    <tr key={sid}>
                      <td>
                        <a href={detailHref}><code>{sid}</code></a>
                      </td>
                      <td>{Math.round(elo)}</td>
                      <td>{pilotStatus}</td>
                      <td>
                        {fileHref ? (
                          <a href={fileHref}><code>{filename}</code></a>
                        ) : (
                          <code>{filename || "."}</code>
                        )}
                        {evolved.length > 0 && (
                          <span className="ml-2 text-white/40 text-xs">
                            → {evolved.map((e) => {
                              const eHref = `/docs/petri/seeds/${run.run_id}/${e}/`;
                              return (
                                <a key={e} href={eHref} className="mr-1"><code>{e}</code></a>
                              );
                            })}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}

        <h3>{costHeading}</h3>
        <table>
          <tbody>
            <tr><th>total USD</th><td>{fmtUSD(asNumber(stateObj.usd_spent))}</td></tr>
            <tr><th>prompt_tokens</th><td>{fmtInt(asNumber(stateObj.prompt_tokens))}</td></tr>
            <tr><th>completion_tokens</th><td>{fmtInt(asNumber(stateObj.completion_tokens))}</td></tr>
            <tr>
              <th>{locale === "ko" ? "iter / max" : "iters / max"}</th>
              <td>{asNumber(stateObj.current_iteration)} / {asNumber(stateObj.max_iterations)}</td>
            </tr>
            <tr>
              <th>literature_snapshots</th>
              <td>{Object.keys(asObject(stateObj.literature_snapshots)).length}</td>
            </tr>
            <tr>
              <th>debate_transcripts</th>
              <td>{Object.keys(asObject(stateObj.debate_transcripts)).length}</td>
            </tr>
          </tbody>
        </table>

        {sessionSummary && (
          <>
            <h3>{summaryHeading}</h3>
            <p>{sessionSummary}</p>
          </>
        )}

        {nextGenPriors.length > 0 && (
          <>
            <h3>{priorsHeading}</h3>
            <table>
              <thead>
                <tr>
                  <th>target_dim</th>
                  <th>weight</th>
                  <th>{locale === "ko" ? "근거" : "rationale"}</th>
                </tr>
              </thead>
              <tbody>
                {nextGenPriors.map((p, idx) => {
                  const pObj = asObject(p);
                  return (
                    <tr key={`${asString(pObj.target_dim)}-${idx}`}>
                      <td><code>{asString(pObj.target_dim)}</code></td>
                      <td>{asNumber(pObj.weight).toFixed(2)}</td>
                      <td>{asString(pObj.rationale)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}

        {Object.keys(evolutionYield).length > 0 && (
          <>
            <h3>{yieldHeading}</h3>
            <table>
              <tbody>
                <tr>
                  <th>{locale === "ko" ? "시도" : "attempted"}</th>
                  <td>{fmtInt(asNumber(evolutionYield.attempted))}</td>
                </tr>
                <tr>
                  <th>{locale === "ko" ? "성공" : "successful"}</th>
                  <td>{fmtInt(asNumber(evolutionYield.successful))}</td>
                </tr>
              </tbody>
            </table>
          </>
        )}

        {Object.keys(eloDist).length > 0 && (
          <>
            <h3>{eloHeading}</h3>
            <table>
              <tbody>
                <tr><th>min</th><td>{fmtInt(asNumber(eloDist.min))}</td></tr>
                <tr><th>p50</th><td>{fmtInt(asNumber(eloDist.p50))}</td></tr>
                <tr><th>p95</th><td>{fmtInt(asNumber(eloDist.p95))}</td></tr>
              </tbody>
            </table>
          </>
        )}
      </div>
    </details>
  );
}

export default function Page() {
  const runs = loadRuns();
  const totalRuns = runs.length;
  const totalCandidates = runs.reduce((a, r) => a + r.run.candidates_drafted, 0);
  const totalSurvivors = runs.reduce((a, r) => a + r.run.survivors_count, 0);
  const totalCost = runs.reduce((a, r) => a + r.run.usd_spent, 0);

  return (
    <DocsShell
      slug="petri/seeds"
      title="Seed Generation Runs"
      titleKo="Seed 생성 Run"
      summary={`${totalRuns} runs · ${totalCandidates} candidates drafted · ${totalSurvivors} survived · ${fmtUSD(totalCost)} total spend.`}
      summaryKo={`${totalRuns}개 run · ${totalCandidates}개 후보 생성 · ${totalSurvivors}개 생존 · ${fmtUSD(totalCost)} 총 비용.`}
    >
      <Bi
        ko={
          <>
            <p>
              <strong>Reference:</strong> self-improving loop 의 seed-generation 파이프라인이 매 generation 마다 산출한 결과를
              <code>docs/petri-bundle/seeds/</code> 에 git-tracked snapshot 으로 publish 합니다. 본 페이지는 build time 에
              <code>listing.json</code> + per-run <code>state.json</code> / <code>survivors.json</code> / <code>meta_review.json</code>
              을 읽어 dashboard 로 렌더링합니다.
            </p>
            <p>
              raw 파일을 직접 보려면 <a href={RAW_BUNDLE_URL}><code>{RAW_BUNDLE_URL}</code></a> 의 정적 viewer 또는 per-run
              디렉토리를 사용. inspect_ai <code>.eval</code> 아카이브 viewer 는 <a href="/petri-bundle/">/geode/petri-bundle/</a> 에 별도.
            </p>

            <h2>전체 Run</h2>
            <RunsTable runs={runs} locale="ko" />

            <h2>Run 별 상세</h2>
            <p>각 row 를 펼치면 survivors / 비용 / meta-review / next-gen prior / Elo 분포가 표시됩니다.</p>
            {runs.length === 0 ? (
              <p><em>아직 published 된 run 이 없습니다. <code>docs/petri-bundle/seeds/listing.json</code> 을 확인하세요.</em></p>
            ) : (
              runs.map((r) => <RunDetailBlock key={r.run.run_id} detail={r} locale="ko" />)
            )}

            <h2>SoT 와 파이프라인</h2>
            <ul>
              <li>seed-generation 소스: <code>plugins/seed_generation/orchestrator.py</code> (8-phase: supervisor → generator → proximity → critic → pilot → ranker → evolver → meta_reviewer)</li>
              <li>bundle 동기화: <code>plugins/seed_generation/bundle_sync.py</code> 가 run 종료 시 결과를 <code>docs/petri-bundle/seeds/&lt;run_id&gt;/</code> 로 mirror</li>
              <li>관련 plan: <a href="/geode/docs/capabilities/seed-pipeline">Seed Pipeline</a> · <a href="/geode/docs/petri/scenarios">Petri Scenarios</a></li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              <strong>Reference:</strong> the self-improving loop&apos;s seed-generation pipeline publishes per-generation results
              as git-tracked snapshots under <code>docs/petri-bundle/seeds/</code>. This page reads
              <code>listing.json</code> + per-run <code>state.json</code> / <code>survivors.json</code> / <code>meta_review.json</code>
              at build time and renders them as a dashboard.
            </p>
            <p>
              For raw files use the static viewer at <a href={RAW_BUNDLE_URL}><code>{RAW_BUNDLE_URL}</code></a> or browse the
              per-run directory. The inspect_ai <code>.eval</code> archive viewer lives separately at <a href="/petri-bundle/">/geode/petri-bundle/</a>.
            </p>

            <h2>All runs</h2>
            <RunsTable runs={runs} locale="en" />

            <h2>Per-run detail</h2>
            <p>Expand each row for survivors / cost / meta-review / next-gen priors / Elo distribution.</p>
            {runs.length === 0 ? (
              <p><em>No published runs yet. Check <code>docs/petri-bundle/seeds/listing.json</code>.</em></p>
            ) : (
              runs.map((r) => <RunDetailBlock key={r.run.run_id} detail={r} locale="en" />)
            )}

            <h2>Source &amp; pipeline</h2>
            <ul>
              <li>seed-generation source: <code>plugins/seed_generation/orchestrator.py</code> (8-phase: supervisor → generator → proximity → critic → pilot → ranker → evolver → meta_reviewer)</li>
              <li>bundle sync: <code>plugins/seed_generation/bundle_sync.py</code> mirrors completed runs into <code>docs/petri-bundle/seeds/&lt;run_id&gt;/</code></li>
              <li>related: <a href="/geode/docs/capabilities/seed-pipeline">Seed Pipeline</a> · <a href="/geode/docs/petri/scenarios">Petri Scenarios</a></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
