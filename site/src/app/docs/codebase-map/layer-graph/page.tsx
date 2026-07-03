import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import layerGraph from "@/data/geode/layer-graph.json";

export const metadata = { title: "Layer architecture graph — GEODE Docs" };

const { meta, nodes, edges, topEdges, hubs, isolated, tour } = layerGraph;
const maxDeg = Math.max(...nodes.map((n) => n.degree), 1);

// Axolotl-Rose role → token mapping. Petri-blue is deliberately excluded — it
// is scoped to the 04-self-improving section only (site/DESIGN.md §2).
const ROLE_STROKE: Record<string, string> = {
  runtime: "var(--acc-artifact)",
  tests: "var(--acc-line)",
  docs: "var(--acc-aqua)",
  config: "var(--ink-3)",
};

function fillOpacity(degree: number, role: string): number {
  if (role === "tests") return 0.9;
  if (degree === 0) return 0.1;
  return Math.round((0.12 + 0.32 * (degree / maxDeg)) * 100) / 100;
}

/** The inline layer graph. Language-neutral; reads only from layer-graph.json. */
function LayerGraphSvg() {
  return (
    <div style={{ overflowX: "auto", margin: "1.5rem 0" }}>
      <svg
        viewBox={meta.viewBox}
        role="img"
        aria-label="GEODE layer architecture: 14 analyzed layers sized by file count, connected by cross-layer import edges."
        style={{
          width: "100%",
          minWidth: 620,
          height: "auto",
          background: "var(--paper-2)",
          border: "1px solid var(--rule)",
          borderRadius: 12,
        }}
        fontFamily="var(--font-sans), system-ui, sans-serif"
      >
        {/* edges */}
        <g strokeLinecap="round">
          {edges.map((e, i) => (
            <line
              key={`e${i}`}
              x1={e.x1}
              y1={e.y1}
              x2={e.x2}
              y2={e.y2}
              stroke={e.top ? "var(--acc-line)" : "var(--acc-artifact)"}
              strokeWidth={e.strokeWidth}
              strokeOpacity={e.top ? Math.min(0.85, e.opacity + 0.25) : e.opacity}
            />
          ))}
        </g>
        {/* top-5 weight labels */}
        <g>
          {edges
            .filter((e) => e.top)
            .map((e, i) => (
              <g key={`t${i}`}>
                <rect
                  x={e.mx - 15}
                  y={e.my - 9}
                  width={30}
                  height={17}
                  rx={4}
                  fill="var(--paper)"
                  stroke="var(--acc-line)"
                  strokeOpacity={0.55}
                />
                <text
                  x={e.mx}
                  y={e.my + 3.5}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={700}
                  fill="var(--acc-line)"
                >
                  {e.weight}
                </text>
              </g>
            ))}
        </g>
        {/* nodes */}
        <g>
          {nodes.map((n) => {
            const isTests = n.role === "tests";
            return (
              <g key={n.id}>
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={n.r}
                  fill={ROLE_STROKE[n.role]}
                  fillOpacity={fillOpacity(n.degree, n.role)}
                  stroke={ROLE_STROKE[n.role]}
                  strokeWidth={1.5}
                />
                {isTests ? (
                  <>
                    <text x={n.x} y={n.y + 3} textAnchor="middle" fontSize={13} fontWeight={700} fill="var(--paper)">
                      {n.short}
                    </text>
                    <text x={n.x} y={n.y + 19} textAnchor="middle" fontSize={10} fill="var(--paper)" fillOpacity={0.85}>
                      {n.fileCount}
                    </text>
                  </>
                ) : (
                  <>
                    <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--ink-1)">
                      {n.fileCount}
                    </text>
                    <text x={n.x} y={n.y + n.r + 14} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--ink-2)">
                      {n.short}
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.25rem 1.25rem",
          marginTop: "0.6rem",
          fontSize: "0.72rem",
          color: "var(--ink-3)",
        }}
      >
        <span>◯ size = files in the layer</span>
        <span>— edge = cross-layer imports (thicker = more)</span>
        <span style={{ color: "var(--acc-line)" }}>▬ gold = the 5 heaviest, labelled</span>
        <span style={{ color: "var(--acc-artifact)" }}>● runtime</span>
        <span style={{ color: "var(--acc-line)" }}>● tests</span>
        <span style={{ color: "var(--acc-aqua)" }}>● docs / site</span>
        <span style={{ color: "var(--ink-3)" }}>● config</span>
      </div>
    </div>
  );
}

const KIND_LABEL: Record<string, string> = {
  file: "src",
  document: "doc",
  config: "config",
  service: "svc",
  resource: "res",
};

export default function Page() {
  return (
    <DocsShell
      slug="codebase-map/layer-graph"
      title="Layer architecture graph"
      titleKo="레이어 아키텍처 그래프"
      summary="A generation-date snapshot of the repository, extracted by Understand-Anything: 14 analyzed layers sized by file count, drawn over their cross-layer import edges, with a seven-step reading tour. Every count is a snapshot label, not a claim."
      summaryKo="Understand-Anything가 추출한 저장소의 특정 시점 스냅숏입니다. 분석된 14개 레이어를 파일 수 크기로, 레이어를 가로지르는 import 의존을 엣지로 그리고, 7단계 읽기 투어를 붙였습니다. 모든 수치는 주장이 아니라 스냅숏 라벨입니다."
    >
      <Bi
        ko={
          <p>
            이 페이지는 손으로 그린 다이어그램이 아닙니다. Understand-Anything가
            저장소를 정적 분석해 만든 지식 그래프에서, 파일 수준 노드를 14개
            레이어로 묶고 <code>imports</code> 엣지만 레이어 간으로 집계한
            결과입니다. 원본 그래프는 노드 {meta.graph.nodes.toLocaleString()}
            개로 커서 페이지에 싣지 않고, 집계 스크립트가 만든 소형 JSON
            (<code>src/data/geode/layer-graph.json</code>) 하나만 소비합니다.
          </p>
        }
        en={
          <p>
            This page is not hand-drawn. It reads a knowledge graph that
            Understand-Anything built by statically analyzing the repository:
            file-level nodes grouped into 14 layers, with only the{" "}
            <code>imports</code> edges aggregated across layer boundaries. The
            raw graph is too large to ship ({meta.graph.nodes.toLocaleString()}{" "}
            nodes), so the page consumes a single small JSON emitted by the
            aggregation script (<code>src/data/geode/layer-graph.json</code>).
          </p>
        }
      />

      <LayerGraphSvg />

      <Bi
        ko={
          <p>
            노드 크기는 레이어의 파일 수, 엣지 굵기는 두 레이어 사이의 import
            횟수입니다. 방향은 접었고(양방향 합), 가장 굵은 5개만 금색으로
            라벨을 답니다. 같은 레이어 안의 import는 레이어 간 그래프에서
            빠집니다.
          </p>
        }
        en={
          <p>
            Node size is the layer&apos;s file count; edge thickness is the
            number of imports between two layers. Direction is folded (both
            ways summed), and only the five heaviest edges carry a gold label.
            Imports within a single layer are excluded from this cross-layer
            view.
          </p>
        }
      />

      <h2>
        <Bi ko="가장 굵은 의존 5개" en="The five heaviest dependencies" />
      </h2>
      <ol>
        {topEdges.map((t) => (
          <li key={t.rank}>
            <strong>{t.weight}</strong> — {t.aName} <Bi ko="↔" en="↔" /> {t.bName}
          </li>
        ))}
      </ol>
      <Bi
        ko={
          <p>
            다섯 개가 모두 Tests에 걸립니다. 이것은 데이터 아티팩트가 아니라
            구조입니다. 테스트 스위트는 각 런타임 레이어를 직접 import하므로,
            레이어 간 import 그래프에서 가장 넓게 뻗는 노드가 됩니다.
          </p>
        }
        en={
          <p>
            All five touch Tests. That is structure, not a data artifact: the
            test suite imports each runtime layer directly, which makes it the
            widest-reaching node in the cross-layer import graph.
          </p>
        }
      />

      <h2>
        <Bi ko="허브와 고립 레이어" en="Hubs and isolated layers" />
      </h2>
      <ul>
        {hubs.map((h) => (
          <li key={h.id}>
            <strong>{h.name}</strong> ({h.importsIn}
            <Bi ko=" 인" en=" in" /> / {h.importsOut}
            <Bi ko=" 아웃" en=" out" />) — {h.note}
          </li>
        ))}
        {isolated.map((n) => (
          <li key={n.id}>
            <strong>{n.name}</strong> ({n.fileCount}
            <Bi ko=" 파일" en=" files" />, 0 <Bi ko="엣지" en="edges" />) — {n.note}
          </li>
        ))}
      </ul>

      <h2>
        <Bi ko="레이어별 수치" en="Layer-by-layer" />
      </h2>
      <p style={{ fontSize: "0.8rem", color: "var(--ink-3)", marginTop: "-0.5rem" }}>
        <Bi
          ko={`스냅숏 ${meta.snapshotDate}. Files = 분석된 파일 수, In/Out = 레이어 간 import, Cross-degree = In+Out.`}
          en={`Snapshot ${meta.snapshotDate}. Files = analyzed file count, In/Out = cross-layer imports, Cross-degree = In+Out.`}
        />
      </p>
      <table>
        <thead>
          <tr>
            <th>Layer</th>
            <th style={{ textAlign: "right" }}>Files</th>
            <th style={{ textAlign: "right" }}>In</th>
            <th style={{ textAlign: "right" }}>Out</th>
            <th style={{ textAlign: "right" }}>Cross-degree</th>
          </tr>
        </thead>
        <tbody>
          {[...nodes]
            .sort((a, b) => b.degree - a.degree)
            .map((n) => (
              <tr key={n.id}>
                <td>{n.name}</td>
                <td style={{ textAlign: "right" }}>{n.fileCount}</td>
                <td style={{ textAlign: "right" }}>{n.importsIn}</td>
                <td style={{ textAlign: "right" }}>{n.importsOut}</td>
                <td style={{ textAlign: "right" }}>
                  <strong>{n.degree}</strong>
                </td>
              </tr>
            ))}
        </tbody>
      </table>

      <h2>
        <Bi ko="읽기 투어 (7단계)" en="Reading tour (7 steps)" />
      </h2>
      <Bi
        ko={
          <p>
            그래프의 tour는 저장소를 처음 여는 사람에게 권하는 읽기 순서입니다.
            정체성 문서에서 시작해 실행 루프, 도구, 프롬프트/프로바이더, 배선,
            감사 플러그인을 지나 공개 사이트에서 끝납니다.
          </p>
        }
        en={
          <p>
            The graph&apos;s tour is a recommended reading order for someone
            opening the repository for the first time: start at the identity
            documents, then the execution loop, tools, the prompt/provider
            stack, wiring, the audit plugin, and end at the public site.
          </p>
        }
      />
      <ol>
        {tour.map((s) => (
          <li key={s.order} style={{ marginBottom: "0.75rem" }}>
            <strong>{s.title}</strong>. {s.description}
            <div style={{ marginTop: "0.3rem" }}>
              {s.modules.map((m, i) => (
                <code
                  key={i}
                  style={{
                    display: "inline-block",
                    marginRight: "0.4rem",
                    marginBottom: "0.25rem",
                    fontSize: "0.74rem",
                  }}
                >
                  <span style={{ color: "var(--ink-3)" }}>{KIND_LABEL[m.kind] ?? m.kind}:</span> {m.path}
                </code>
              ))}
            </div>
          </li>
        ))}
      </ol>

      <h2>
        <Bi ko="이 지도는 어떻게 생성되나" en="How this map is generated" />
      </h2>
      <p
        style={{
          fontSize: "0.78rem",
          color: "var(--ink-3)",
          borderLeft: "2px solid var(--rule)",
          paddingLeft: "0.75rem",
        }}
      >
        {meta.generatedLabel}
      </p>
      <Bi
        ko={
          <p>
            재생성은 두 단계입니다. 먼저 Understand-Anything v
            {meta.toolVersion}로 저장소를 다시 스캔해{" "}
            <code>.understand-anything/knowledge-graph.json</code>를 갱신하고,
            이어서 사이트에서 집계 스크립트를 돌립니다. 그래프 원본은
            로컬에서만 생성되며 커밋하지 않습니다(worktree에서는{" "}
            <code>KG_JSON</code>로 절대 경로를 넘깁니다).
          </p>
        }
        en={
          <p>
            Regeneration is two steps. First, an Understand-Anything v
            {meta.toolVersion} re-scan of the repository refreshes{" "}
            <code>.understand-anything/knowledge-graph.json</code>; then the
            aggregation script runs from the site. The raw graph is a local-only
            artifact and is never committed (in a worktree, pass its absolute
            path via <code>KG_JSON</code>).
          </p>
        }
      />
      <pre>
        <code>{`# 1. rescan (Understand-Anything v${meta.toolVersion}) -> .understand-anything/knowledge-graph.json
# 2. aggregate into the small JSON + the deck SVG:
${meta.regenerateCommand}`}</code>
      </pre>
      <Bi
        ko={
          <p>
            같은 집계에서 덱용 라이트 팔레트 SVG도 함께 만들어져{" "}
            <code>public/diagrams/layer-graph-deck-light.svg</code>에
            저장됩니다.
          </p>
        }
        en={
          <p>
            The same aggregation also emits a light-palette SVG for slide decks
            at <code>public/diagrams/layer-graph-deck-light.svg</code>.
          </p>
        }
      />

      <h2>
        <Bi ko="더 읽을거리" en="Read next" />
      </h2>
      <ul>
        <li>
          <a href="/geode/docs/develop/architecture">
            <Bi ko="아키텍처 심화" en="Architecture deep-dive" />
          </a>
          . <Bi ko="레이어를 가로지르는 데이터 흐름." en="Data flows across the layers." />
        </li>
        <li>
          <a href="/geode/docs/architecture/system-index">
            <Bi ko="시스템 색인" en="System index" />
          </a>
          . <Bi ko="모든 서브시스템과 파일 경로의 평면 카탈로그." en="The flat catalog of every subsystem and its path." />
        </li>
        <li>
          <a href="/geode/docs/explanation/4-layer">
            <Bi ko="왜 5계층인가" en="Why five layers" />
          </a>
          . <Bi ko="경계가 왜 그 자리에 있는지." en="Why the boundaries fall where they do." />
        </li>
      </ul>
    </DocsShell>
  );
}
