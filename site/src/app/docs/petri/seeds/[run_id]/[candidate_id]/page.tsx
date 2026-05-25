import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";
import { marked } from "marked";
import { notFound } from "next/navigation";
import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

const REPO_ROOT = path.join(process.cwd(), "..");
const SEEDS_DIR = path.join(REPO_ROOT, "docs", "petri-bundle", "seeds");
const RAW_BUNDLE_URL = "/petri-bundle/seeds/";

type Candidate = { run_id: string; candidate_id: string; kind: "candidate" | "evolved" };

function listCandidates(): Candidate[] {
  if (!fs.existsSync(SEEDS_DIR)) return [];
  const runs = fs
    .readdirSync(SEEDS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name);
  const out: Candidate[] = [];
  for (const run_id of runs) {
    for (const kind of ["candidates", "candidates_evolved"] as const) {
      const dir = path.join(SEEDS_DIR, run_id, kind);
      if (!fs.existsSync(dir)) continue;
      for (const f of fs.readdirSync(dir)) {
        if (!f.endsWith(".md")) continue;
        out.push({
          run_id,
          candidate_id: f.replace(/\.md$/, ""),
          kind: kind === "candidates" ? "candidate" : "evolved",
        });
      }
    }
  }
  return out;
}

export function generateStaticParams() {
  return listCandidates().map((c) => ({ run_id: c.run_id, candidate_id: c.candidate_id }));
}

type LoadedSeed = {
  run_id: string;
  candidate_id: string;
  kind: "candidate" | "evolved";
  frontmatter: Record<string, unknown>;
  body_html: string;
  raw_path: string;
  critic: Record<string, unknown> | null;
  pilot: Record<string, unknown> | null;
  parent_id: string | null;
  evolved_children: string[];
  elo_rating: number | null;
};

function asObject(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}
function asString(v: unknown): string {
  return typeof v === "string" ? v : "";
}
function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function loadSeed(run_id: string, candidate_id: string): LoadedSeed | null {
  const runDir = path.join(SEEDS_DIR, run_id);
  if (!fs.existsSync(runDir)) return null;
  // Resolve which directory the candidate lives in. candidates_evolved wins if
  // the same id ever lands in both (the evolved file is the newer signal).
  const tries: { dir: string; kind: "candidate" | "evolved" }[] = [
    { dir: "candidates_evolved", kind: "evolved" },
    { dir: "candidates", kind: "candidate" },
  ];
  let mdPath = "";
  let kind: "candidate" | "evolved" = "candidate";
  for (const t of tries) {
    const p = path.join(runDir, t.dir, `${candidate_id}.md`);
    if (fs.existsSync(p)) {
      mdPath = p;
      kind = t.kind;
      break;
    }
  }
  if (!mdPath) return null;
  const raw = fs.readFileSync(mdPath, "utf-8");
  const parsed = matter(raw);
  const body_html = marked.parse(parsed.content, { async: false }) as string;
  const raw_path =
    `${RAW_BUNDLE_URL}${run_id}/` +
    (kind === "evolved" ? "candidates_evolved" : "candidates") +
    `/${candidate_id}.md`;

  // Optional cross-references from state.json.
  const statePath = path.join(runDir, "state.json");
  let critic: Record<string, unknown> | null = null;
  let pilot: Record<string, unknown> | null = null;
  let parent_id: string | null = null;
  const evolved_children: string[] = [];
  let elo_rating: number | null = null;
  if (fs.existsSync(statePath)) {
    try {
      const state = JSON.parse(fs.readFileSync(statePath, "utf-8")) as Record<string, unknown>;
      const reflections = asObject(state.reflections);
      if (reflections[candidate_id]) critic = asObject(reflections[candidate_id]);
      const pilotScores = asObject(state.pilot_scores);
      if (pilotScores[candidate_id]) pilot = asObject(pilotScores[candidate_id]);
      const evolved = asArray(state.evolved_candidates);
      for (const e of evolved) {
        const eo = asObject(e);
        if (asString(eo.parent_id) === candidate_id) {
          evolved_children.push(asString(eo.id));
        }
        if (asString(eo.id) === candidate_id) parent_id = asString(eo.parent_id) || null;
      }
    } catch {
      // tolerate malformed state.json
    }
  }
  const survivorsPath = path.join(runDir, "survivors.json");
  if (fs.existsSync(survivorsPath)) {
    try {
      const surv = JSON.parse(fs.readFileSync(survivorsPath, "utf-8")) as Record<string, unknown>;
      for (const s of asArray(surv.survivors)) {
        const so = asObject(s);
        if (asString(so.id) === candidate_id) {
          elo_rating = asNumber(so.elo_rating);
        }
      }
    } catch {
      // tolerate
    }
  }

  return {
    run_id,
    candidate_id,
    kind,
    frontmatter: parsed.data as Record<string, unknown>,
    body_html,
    raw_path,
    critic,
    pilot,
    parent_id,
    evolved_children,
    elo_rating,
  };
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ run_id: string; candidate_id: string }>;
}) {
  const { candidate_id } = await params;
  return { title: `Seed ${candidate_id} · GEODE Docs` };
}

export default async function Page({
  params,
}: {
  params: Promise<{ run_id: string; candidate_id: string }>;
}) {
  const { run_id, candidate_id } = await params;
  const seed = loadSeed(run_id, candidate_id);
  if (!seed) notFound();

  const fm = seed.frontmatter;
  const target_dims = asArray(fm.target_dims).map((v) => asString(v)).filter(Boolean);
  const tags = asArray(fm.tags).map((v) => asString(v)).filter(Boolean);
  const refs = asArray(fm.references).map((v) => asString(v)).filter(Boolean);
  const category = asString(fm.category);
  const name = asString(fm.name);
  const paraphrase = fm.paraphrase_seed;

  const pilotMeans = asObject(asObject(seed.pilot).dim_means);
  const dimMeanRows = Object.entries(pilotMeans)
    .filter(([, v]) => typeof v === "number")
    .sort((a, b) => (b[1] as number) - (a[1] as number));
  const criticStrengths = asArray(asObject(seed.critic).strengths).map(asString).filter(Boolean);
  const criticWeaknesses = asArray(asObject(seed.critic).weaknesses).map(asString).filter(Boolean);
  const judgeRisk = asString(asObject(seed.critic).judge_risk);
  const intendedMatch = asObject(seed.critic).intended_dim_match;
  const targetDimsActual = asArray(asObject(seed.critic).target_dims_actual).map(asString).filter(Boolean);
  const rewriteSection = asString(asObject(seed.critic).rewrite_section);

  const title = name || candidate_id;
  const titleKo = title;
  const subhead = `${seed.kind === "evolved" ? "Evolved seed" : "Candidate seed"} · ${seed.run_id}`;
  const subheadKo = `${seed.kind === "evolved" ? "진화 시드" : "후보 시드"} · ${seed.run_id}`;

  return (
    <DocsShell
      slug="petri/seeds"
      title={title}
      titleKo={titleKo}
      summary={subhead}
      summaryKo={subheadKo}
    >
      <Bi
        ko={
          <SeedDetail
            locale="ko"
            seed={seed}
            target_dims={target_dims}
            target_dims_actual={targetDimsActual}
            tags={tags}
            refs={refs}
            category={category}
            paraphrase_seed={paraphrase}
            dim_mean_rows={dimMeanRows}
            critic_strengths={criticStrengths}
            critic_weaknesses={criticWeaknesses}
            judge_risk={judgeRisk}
            intended_match={intendedMatch}
            rewrite_section={rewriteSection}
          />
        }
        en={
          <SeedDetail
            locale="en"
            seed={seed}
            target_dims={target_dims}
            target_dims_actual={targetDimsActual}
            tags={tags}
            refs={refs}
            category={category}
            paraphrase_seed={paraphrase}
            dim_mean_rows={dimMeanRows}
            critic_strengths={criticStrengths}
            critic_weaknesses={criticWeaknesses}
            judge_risk={judgeRisk}
            intended_match={intendedMatch}
            rewrite_section={rewriteSection}
          />
        }
      />
    </DocsShell>
  );
}

type DetailProps = {
  locale: "ko" | "en";
  seed: LoadedSeed;
  target_dims: string[];
  target_dims_actual: string[];
  tags: string[];
  refs: string[];
  category: string;
  paraphrase_seed: unknown;
  dim_mean_rows: [string, unknown][];
  critic_strengths: string[];
  critic_weaknesses: string[];
  judge_risk: string;
  intended_match: unknown;
  rewrite_section: string;
};

function SeedDetail(props: DetailProps) {
  const { locale, seed } = props;
  const t = (ko: string, en: string) => (locale === "ko" ? ko : en);

  return (
    <>
      <h2>{t("Frontmatter", "Frontmatter")}</h2>
      <table>
        <tbody>
          <tr>
            <th>{t("후보 id", "candidate_id")}</th>
            <td><code>{seed.candidate_id}</code></td>
          </tr>
          <tr>
            <th>{t("종류", "kind")}</th>
            <td>{seed.kind}</td>
          </tr>
          {props.category && (
            <tr>
              <th>category</th>
              <td>{props.category}</td>
            </tr>
          )}
          <tr>
            <th>target_dims</th>
            <td>{props.target_dims.map((d) => <code key={d} className="mr-2">{d}</code>)}</td>
          </tr>
          {props.tags.length > 0 && (
            <tr>
              <th>tags</th>
              <td>{props.tags.map((d) => <code key={d} className="mr-2">{d}</code>)}</td>
            </tr>
          )}
          {props.refs.length > 0 && (
            <tr>
              <th>references</th>
              <td>{props.refs.map((d) => <code key={d} className="mr-2">{d}</code>)}</td>
            </tr>
          )}
          {props.paraphrase_seed !== undefined && (
            <tr>
              <th>paraphrase_seed</th>
              <td><code>{String(props.paraphrase_seed)}</code></td>
            </tr>
          )}
          {seed.elo_rating !== null && (
            <tr>
              <th>elo_rating</th>
              <td>{Math.round(seed.elo_rating)}</td>
            </tr>
          )}
          {seed.parent_id && (
            <tr>
              <th>parent_id</th>
              <td>
                <a href={`./${seed.parent_id}/`}><code>{seed.parent_id}</code></a>
              </td>
            </tr>
          )}
          {seed.evolved_children.length > 0 && (
            <tr>
              <th>{t("진화 자식", "evolved children")}</th>
              <td>
                {seed.evolved_children.map((c) => (
                  <a key={c} href={`./${c}/`} className="mr-2"><code>{c}</code></a>
                ))}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {seed.critic && (
        <>
          <h2>{t("Critic", "Critic")}</h2>
          <table>
            <tbody>
              <tr>
                <th>{t("intended dim 일치", "intended_dim_match")}</th>
                <td>{String(props.intended_match)}</td>
              </tr>
              {props.target_dims_actual.length > 0 && (
                <tr>
                  <th>target_dims_actual</th>
                  <td>{props.target_dims_actual.map((d) => <code key={d} className="mr-2">{d}</code>)}</td>
                </tr>
              )}
              {props.judge_risk && (
                <tr>
                  <th>judge_risk</th>
                  <td>{props.judge_risk}</td>
                </tr>
              )}
              {props.critic_strengths.length > 0 && (
                <tr>
                  <th>{t("강점", "strengths")}</th>
                  <td>
                    <ul>
                      {props.critic_strengths.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  </td>
                </tr>
              )}
              {props.critic_weaknesses.length > 0 && (
                <tr>
                  <th>{t("약점", "weaknesses")}</th>
                  <td>
                    <ul>
                      {props.critic_weaknesses.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  </td>
                </tr>
              )}
              {props.rewrite_section && (
                <tr>
                  <th>rewrite_section</th>
                  <td>{props.rewrite_section}</td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}

      {seed.pilot && (
        <>
          <h2>{t("Pilot", "Pilot")}</h2>
          {props.dim_mean_rows.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>dim</th>
                  <th>mean</th>
                </tr>
              </thead>
              <tbody>
                {props.dim_mean_rows.map(([dim, mean]) => (
                  <tr key={dim}>
                    <td><code>{dim}</code></td>
                    <td>{typeof mean === "number" ? mean.toFixed(2) : "."}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p>{t("dim_means 없음 — pilot 가 실패했거나 데이터 비어 있음.", "no dim_means — pilot failed or empty.")}</p>
          )}
        </>
      )}

      <h2>{t("본문", "Body")}</h2>
      <div className="seed-md" dangerouslySetInnerHTML={{ __html: seed.body_html }} />

      <h2>{t("원본", "Source")}</h2>
      <ul>
        <li>
          <a href={seed.raw_path}>{t("raw `.md` 다운로드", "raw `.md` download")}</a>
        </li>
        <li>
          <a href={`/petri-bundle/landing.html`}>{t("Petri bundle 허브", "Petri bundle hub")}</a>
        </li>
        <li>
          <a href={`/petri-bundle/`}>{t("Eval 로그 viewer", "Eval log viewer")}</a>
        </li>
      </ul>
    </>
  );
}
