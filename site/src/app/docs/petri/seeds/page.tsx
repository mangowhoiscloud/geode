import fs from "node:fs";
import path from "node:path";
import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Seed Generation Runs · GEODE Docs" };

// At build time, process.cwd() is the site/ directory.
// Seeds live one level up under docs/self-improving/petri-bundle/seeds/ in the repo root.
const REPO_ROOT = path.join(process.cwd(), "..");
const SEEDS_DIR = path.join(REPO_ROOT, "docs", "self-improving", "petri-bundle", "seeds");
const RAW_BUNDLE_URL = "/geode/self-improving/petri-bundle/seeds/";

function candidateFileExists(runId: string, candidateId: string): boolean {
  for (const dir of ["candidates", "candidates_evolved"]) {
    if (fs.existsSync(path.join(SEEDS_DIR, runId, dir, `${candidateId}.md`))) return true;
  }
  return false;
}


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
      ? ["run_id", "gen_tag", "target_dim", "상태", "draft → surv", "evolved", "iters"]
      : ["run_id", "gen_tag", "target_dim", "status", "draft → surv", "evolved", "iters"];
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
  const costHeading = locale === "ko" ? "Run 집계" : "Run rollup";
  const summaryHeading = locale === "ko" ? "메타 리뷰 요약" : "Meta-review summary";
  const priorsHeading = locale === "ko" ? "다음 세대 prior" : "Next-gen priors";
  const yieldHeading = locale === "ko" ? "진화 산출" : "Evolution yield";
  const eloHeading = locale === "ko" ? "Elo 분포" : "Elo distribution";
  const rawLinkLabel = locale === "ko" ? "raw 번들" : "raw bundle";
  const headerKo = `${run.gen_tag} · target_dim=${run.target_dim}`;

  return (
    <details id={`run-${run.run_id}`} className="my-4 border border-[var(--rule)] rounded-md">
      <summary className="cursor-pointer px-4 py-3 hover:bg-[var(--paper-2)] select-none">
        <code className="text-[var(--acc-artifact)]">{run.run_id}</code>
        <span className="ml-3 text-[var(--ink-3)] text-sm">{headerKo}</span>
        {/* GitHub Pages does not serve directory listings, so we link a
            concrete served file (state.json) inside the per-run directory
            instead of `<run_id>/`. PR-SEEDS-PER-RUN-LINK (2026-05-25). */}
        <a
          href={`${RAW_BUNDLE_URL}${run.run_id}/state.json`}
          className="ml-3 text-[var(--ink-3)] text-xs hover:text-[var(--acc-artifact)]"
        >
          [{rawLinkLabel} ↗]
        </a>
      </summary>
      <div className="px-4 py-3 border-t border-[var(--rule-soft)]">
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
                  // survivors.json stores a bundle-relative path
                  // (candidates/ or candidates_evolved/). Use it verbatim so
                  // evolved survivors resolve instead of 404-ing on a forced
                  // candidates/ prefix.
                  const fileHref = candidatePath
                    ? `${RAW_BUNDLE_URL}${run.run_id}/${candidatePath}`
                    : undefined;
                  const evolved = evolvedByParent.get(sid) ?? [];
                  // next.config.ts has `trailingSlash: false` so links must NOT end in `/`.
                  // Link only when the candidate .md exists in the bundle, in
                  // parity with [candidate_id]/generateStaticParams. gen1 runs
                  // list survivors whose files never shipped (bundle sync gap);
                  // a forced link 404s on the deployed site.
                  const detailHref = candidateFileExists(run.run_id, sid)
                    ? `/geode/docs/petri/seeds/${run.run_id}/${sid}`
                    : undefined;
                  return (
                    <tr key={sid}>
                      <td>
                        {detailHref ? (
                          <a href={detailHref}><code>{sid}</code></a>
                        ) : (
                          <code>{sid}</code>
                        )}
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
                          <span className="ml-2 text-[var(--ink-3)] text-xs">
                            → {evolved.map((e) => {
                              if (!candidateFileExists(run.run_id, e)) {
                                return <code key={e} className="mr-1">{e}</code>;
                              }
                              const eHref = `/geode/docs/petri/seeds/${run.run_id}/${e}`;
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

  return (
    <DocsShell
      slug="petri/seeds"
      title="Seed-generation runs"
      titleKo="Seed 생성 런"
      summary={`${totalRuns} runs · ${totalCandidates} candidates drafted · ${totalSurvivors} survived.`}
      summaryKo={`${totalRuns}개 run · ${totalCandidates}개 후보 생성 · ${totalSurvivors}개 생존.`}
    >
      <Bi
        ko={
          <>
            <p>
              자기개선 루프의 seed-generation 파이프라인은 세대마다 산출한
              결과를 <code>docs/self-improving/petri-bundle/seeds/</code>에
              git-tracked 스냅샷으로 공개합니다. 이 페이지는 빌드 시점에{" "}
              <code>listing.json</code>과 run별 <code>state.json</code> /{" "}
              <code>survivors.json</code> / <code>meta_review.json</code>을 읽어
              대시보드로 렌더링합니다.
            </p>
            <p>
              raw 파일은 <a href={RAW_BUNDLE_URL}><code>{RAW_BUNDLE_URL}</code></a>의
              정적 뷰어에서 보거나, run별 <code>state.json</code> /{" "}
              <code>survivors.json</code>을 직접 엽니다. Pages는 디렉토리
              목록을 제공하지 않습니다. inspect_ai <code>.eval</code> 아카이브
              뷰어는{" "}
              <a href="/geode/self-improving/petri-bundle/">/geode/self-improving/petri-bundle/</a>에
              따로 있습니다.
            </p>

            <h2>전체 Run</h2>
            <RunsTable runs={runs} locale="ko" />

            <h2>Run별 상세</h2>
            <p>각 행을 펼치면 survivors, 비용, meta-review, next-gen prior, Elo 분포가 보입니다.</p>
            {runs.length === 0 ? (
              <p><em>아직 공개된 run이 없습니다. <code>docs/self-improving/petri-bundle/seeds/listing.json</code>을 확인하세요.</em></p>
            ) : (
              runs.map((r) => <RunDetailBlock key={r.run.run_id} detail={r} locale="ko" />)
            )}

            <h2>SoT와 파이프라인</h2>
            <ul>
              <li>seed-generation 소스: <code>plugins/seed_generation/orchestrator.py</code> (9-역할: supervisor → literature_review → generator → proximity → critic → pilot → ranker → evolver → meta_reviewer. 상세는 <a href="/geode/docs/capabilities/co-scientist">Seed Scenario Generation</a>)</li>
              <li>bundle 동기화: <code>plugins/seed_generation/bundle_sync.py</code>가 run 종료 시 결과를 <code>docs/self-improving/petri-bundle/seeds/&lt;run_id&gt;/</code>로 동기화합니다</li>
              <li>관련 문서: <a href="/geode/docs/capabilities/seed-pipeline">Seed 파이프라인</a> · <a href="/geode/docs/petri/scenarios">Petri 시나리오</a></li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The self-improving loop&apos;s seed-generation pipeline publishes per-generation results
              as git-tracked snapshots under <code>docs/self-improving/petri-bundle/seeds/</code>. This page reads
              <code>listing.json</code> + per-run <code>state.json</code> / <code>survivors.json</code> / <code>meta_review.json</code>
              at build time and renders them as a dashboard.
            </p>
            <p>
              For raw files use the static viewer at <a href={RAW_BUNDLE_URL}><code>{RAW_BUNDLE_URL}</code></a> or open
              per-run <code>state.json</code> / <code>survivors.json</code> directly (Pages does not serve directory listings).
              The inspect_ai <code>.eval</code> archive viewer lives separately at <a href="/geode/self-improving/petri-bundle/">/geode/self-improving/petri-bundle/</a>.
            </p>

            <h2>All runs</h2>
            <RunsTable runs={runs} locale="en" />

            <h2>Per-run detail</h2>
            <p>Expand each row for survivors / cost / meta-review / next-gen priors / Elo distribution.</p>
            {runs.length === 0 ? (
              <p><em>No published runs yet. Check <code>docs/self-improving/petri-bundle/seeds/listing.json</code>.</em></p>
            ) : (
              runs.map((r) => <RunDetailBlock key={r.run.run_id} detail={r} locale="en" />)
            )}

            <h2>Source &amp; pipeline</h2>
            <ul>
              <li>seed-generation source: <code>plugins/seed_generation/orchestrator.py</code> (nine roles: supervisor → literature_review → generator → proximity → critic → pilot → ranker → evolver → meta_reviewer; details in <a href="/geode/docs/capabilities/co-scientist">Seed Scenario Generation</a>)</li>
              <li>bundle sync: <code>plugins/seed_generation/bundle_sync.py</code> mirrors completed runs into <code>docs/self-improving/petri-bundle/seeds/&lt;run_id&gt;/</code></li>
              <li>related: <a href="/geode/docs/capabilities/seed-pipeline">Seed Pipeline</a> · <a href="/geode/docs/petri/scenarios">Petri Scenarios</a></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
