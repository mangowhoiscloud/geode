"use client";

/**
 * DAG Renderer — 데이터 기반 SVG DAG 생성기
 *
 * 노드 위치를 자동 계산하고, 엣지 곡선을 일관된 bezier로 렌더링합니다.
 * 모든 DAG에서 공유하는 단일 렌더러.
 */

export type DagNode = {
  id: string;
  label: string;
  sub?: string;
  color: string;
  column: number;   // 0-based column position
  row?: number;      // 0 = center, -1/-2 = up, 1/2 = down (for fan-out)
};

export type DagEdge = {
  from: string;
  to: string;
  color?: string;
  dashed?: boolean;
  label?: string;
  animated?: boolean;
};

type Props = {
  nodes: DagNode[];
  edges: DagEdge[];
  loopback?: { from: string; to: string; label?: string; color?: string };
  annotations?: { x: number; y: number; text: string; color?: string }[];
  nodeRadius?: number;
  className?: string;
};

const NODE_R = 28;
const COL_SPACING = 130;
const ROW_SPACING = 65;
const PADDING_X = 50;
const PADDING_Y = 50;
const EDGE_COLOR = "white";
const EDGE_OPACITY = 0.22;

export function DagRenderer({
  nodes,
  edges,
  loopback,
  annotations,
  nodeRadius = NODE_R,
  className,
}: Props) {
  // Calculate layout
  const maxCol = Math.max(...nodes.map((n) => n.column));
  const rows = nodes.filter((n) => n.row !== undefined).map((n) => n.row!);
  const minRow = rows.length > 0 ? Math.min(...rows) : 0;
  const maxRow = rows.length > 0 ? Math.max(...rows) : 0;

  const W = (maxCol + 1) * COL_SPACING + PADDING_X * 2;
  const centerY = PADDING_Y + Math.abs(minRow) * ROW_SPACING + nodeRadius;
  const H = centerY + maxRow * ROW_SPACING + nodeRadius + PADDING_Y + (loopback ? 50 : 10);

  // Node position map
  const pos = new Map<string, { x: number; y: number }>();
  nodes.forEach((n) => {
    const x = PADDING_X + n.column * COL_SPACING;
    const y = centerY + (n.row ?? 0) * ROW_SPACING;
    pos.set(n.id, { x, y });
  });

  // Bezier edge between two points
  function edgePath(x1: number, y1: number, x2: number, y2: number): string {
    if (Math.abs(y1 - y2) < 5) {
      // Horizontal: gentle arc
      const mx = (x1 + x2) / 2;
      return `M${x1},${y1} C${mx},${y1 - 6} ${mx},${y2 - 6} ${x2},${y2}`;
    }
    // Diagonal: smooth S-curve
    const dx = (x2 - x1) * 0.4;
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }

  // Loopback arc (goes below all nodes)
  function loopbackPath(fromPos: { x: number; y: number }, toPos: { x: number; y: number }): string {
    const belowY = H - PADDING_Y + 5;
    return `M${fromPos.x},${fromPos.y + nodeRadius} C${fromPos.x},${belowY} ${toPos.x},${belowY} ${toPos.x},${toPos.y + nodeRadius}`;
  }

  return (
    <div className={`w-full overflow-x-auto -mx-6 px-6 pb-4 ${className || ""}`}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ minWidth: Math.min(W, 560), maxHeight: Math.min(H + 20, 300) }}>
        {/* Edges */}
        {edges.map((e) => {
          const from = pos.get(e.from);
          const to = pos.get(e.to);
          if (!from || !to) return null;

          const x1 = from.x + nodeRadius;
          const y1 = from.y;
          const x2 = to.x - nodeRadius;
          const y2 = to.y;

          return (
            <g key={`${e.from}-${e.to}`}>
              <path
                d={edgePath(x1, y1, x2, y2)}
                fill="none"
                stroke={e.color || EDGE_COLOR}
                strokeOpacity={e.dashed ? 0.25 : EDGE_OPACITY}
                strokeWidth={e.dashed ? 1.2 : 1.2}
                strokeDasharray={e.dashed ? "5 4" : undefined}
                className={e.animated ? "animate-flow" : undefined}
              />
              {e.label && (
                <text
                  x={(from.x + to.x) / 2}
                  y={Math.min(from.y, to.y) - nodeRadius - 8}
                  textAnchor="middle"
                  fill={e.color || EDGE_COLOR}
                  fillOpacity={0.4}
                  fontSize={9}
                  fontFamily="ui-monospace, monospace"
                >
                  {e.label}
                </text>
              )}
            </g>
          );
        })}

        {/* Loopback arc */}
        {loopback && (() => {
          const from = pos.get(loopback.from);
          const to = pos.get(loopback.to);
          if (!from || !to) return null;
          return (
            <g>
              <path
                d={loopbackPath(from, to)}
                fill="none"
                stroke={loopback.color || "#E87080"}
                strokeOpacity={0.25}
                strokeWidth={1.2}
                strokeDasharray="5 4"
                className="animate-flow"
              />
              {loopback.label && (
                <text
                  x={(from.x + to.x) / 2}
                  y={H - PADDING_Y + 18}
                  textAnchor="middle"
                  fill={loopback.color || "#E87080"}
                  fillOpacity={0.45}
                  fontSize={9}
                  fontFamily="ui-monospace, monospace"
                >
                  {loopback.label}
                </text>
              )}
            </g>
          );
        })()}

        {/* Nodes (rendered AFTER edges so they sit on top) */}
        {nodes.map((n) => {
          const p = pos.get(n.id)!;
          return (
            <g key={n.id}>
              <circle
                cx={p.x} cy={p.y} r={nodeRadius}
                fill="#0C1220"
                stroke={n.color}
                strokeWidth={1}
                strokeOpacity={0.45}
              />
              <text
                x={p.x} y={n.sub ? p.y - 3 : p.y + 1}
                textAnchor="middle" dominantBaseline="central"
                fill={n.color}
                fontSize={10}
                fontFamily="ui-monospace, monospace"
                fontWeight={700}
              >
                {n.label}
              </text>
              {n.sub && (
                <text
                  x={p.x} y={p.y + 12}
                  textAnchor="middle"
                  fill={n.color}
                  fillOpacity={0.4}
                  fontSize={8}
                  fontFamily="ui-monospace, monospace"
                >
                  {n.sub}
                </text>
              )}
            </g>
          );
        })}

        {/* Annotations */}
        {annotations?.map((a, i) => (
          <text
            key={i}
            x={a.x}
            y={a.y}
            textAnchor="middle"
            fill={a.color || "white"}
            fillOpacity={0.35}
            fontSize={9}
            fontFamily="ui-monospace, monospace"
          >
            {a.text}
          </text>
        ))}
      </svg>
    </div>
  );
}
