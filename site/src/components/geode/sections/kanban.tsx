"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence, useInView } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { useLocale, t } from "../locale-context";

/* ── Column Definitions ── */
const columns = [
  { id: "backlog", label: "Backlog", color: "#7A8CA8", descKo: "대기. plan 문서 링크, 우선순위 태깅", descEn: "Waiting. Plan doc link, priority tagging" },
  { id: "in-progress", label: "In Progress", color: "#818CF8", descKo: "워크트리 할당됨. .owner에 세션 ID 기록", descEn: "Worktree assigned. Session ID recorded in .owner" },
  { id: "in-review", label: "In Review", color: "#F5C542", descKo: "PR 생성됨. CI 5/5 대기", descEn: "PR created. Awaiting CI 5/5" },
  { id: "done", label: "Done", color: "#34D399", descKo: "main 머지 완료. 세션별 그룹핑", descEn: "Merged to main. Grouped by session" },
];

/* ── Board Rules ── */
const rules = [
  { ruleKo: "main-only write", ruleEn: "main-only write", descKo: "feature/develop 브랜치에서 progress.md 수정 금지. main에서만 업데이트.", descEn: "No progress.md edits on feature/develop branches. Update on main only.", color: "#E87080" },
  { ruleKo: ".owner 격리", ruleEn: ".owner isolation", descKo: "워크트리마다 .owner 파일에 session + task_id 기록. 타 세션 삭제 차단.", descEn: "Each worktree records session + task_id in .owner file. Prevents deletion by other sessions.", color: "#818CF8" },
  { ruleKo: "Backlog→Done 점프 금지", ruleEn: "No Backlog→Done skip", descKo: "반드시 In Progress를 거쳐야 Done. 모든 작업에 실행 흔적 보장.", descEn: "Must go through In Progress before Done. Ensures execution trace for all tasks.", color: "#F5C542" },
  { ruleKo: "3-Checkpoint", ruleEn: "3-Checkpoint", descKo: "Alloc(Step 0) → Free(PR merge) → Cross-check(세션 시작). 누수 탐지.", descEn: "Alloc (Step 0) → Free (PR merge) → Cross-check (session start). Leak detection.", color: "#4ECDC4" },
];

/* ── Example Board Items ── */
interface BoardItem {
  id: string;
  title: string;
  priority?: string;
  plan?: string;
  branch?: string;
  owner?: string;
  pr?: string;
  ci?: string;
  date?: string;
}

const initialItems: Record<number, BoardItem[]> = {
  0: [
    { id: "shared-services", title: "SharedServices 통합", priority: "P1", plan: "docs/plans/shared-services.md" },
    { id: "hook-approval", title: "Hook Approval UI 개선", priority: "P2", plan: "docs/plans/hook-approval.md" },
  ],
  1: [
    { id: "skill-2.0", title: "Skill 2.0 Progressive Disclosure", branch: "feature/skill-2.0", owner: "session=2026-03-29T04:06" },
    { id: "data-path", title: "Data Path Migration", branch: "feature/data-path", owner: "session=2026-03-29T03:15" },
  ],
  2: [
    { id: "sub-process", title: "SubAgent Subprocess Isolation", pr: "PR #523", ci: "5/5 ✓" },
  ],
  3: [
    { id: "en-md", title: "LLM 문서 영어 전환 (39 files)", pr: "PR #522", date: "2026-03-29" },
    { id: "scheduler-fix", title: "Scheduler Hardening 6건", pr: "PR #520", date: "2026-03-28" },
  ],
};

/* ── Migration Sequence ── */
const migrationSequence = [
  { itemId: "sub-process", from: 2, to: 3 },
  { itemId: "data-path", from: 1, to: 2 },
  { itemId: "hook-approval", from: 0, to: 1 },
  { itemId: "skill-2.0", from: 1, to: 2 },
  { itemId: "shared-services", from: 0, to: 1 },
];

/* ── Stats ── */
const stats = [
  { label: "30+ Sessions", color: "#7A8CA8" },
  { label: "190 Modules", color: "#818CF8" },
  { label: "3,422+ Tests", color: "#F5C542" },
  { label: "main-only ✓", color: "#34D399" },
];

/* ── Pulsing Dot for In Progress items ── */
function PulsingDot({ color }: { color: string }) {
  return (
    <span className="relative flex h-2 w-2 shrink-0">
      <span
        className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-50"
        style={{ backgroundColor: color }}
      />
      <span
        className="relative inline-flex h-2 w-2 rounded-full"
        style={{ backgroundColor: color }}
      />
    </span>
  );
}

/* ── Flow Arrow between columns ── */
function FlowArrow() {
  return (
    <div className="hidden md:flex items-center justify-center w-6 shrink-0 self-start mt-10">
      <svg width="20" height="16" viewBox="0 0 20 16" fill="none" className="overflow-visible">
        <path
          d="M0 8h14"
          stroke="white"
          strokeOpacity="0.15"
          strokeWidth="1.5"
          strokeDasharray="3 3"
          className="animate-flow-dash"
        />
        <path d="M12 4l5 4-5 4" stroke="white" strokeOpacity="0.2" strokeWidth="1.5" fill="none" />
      </svg>
    </div>
  );
}

/* ── Single Card Component ── */
function KanbanCard({
  item,
  colIndex,
  color,
  isTransitioning,
}: {
  item: BoardItem;
  colIndex: number;
  color: string;
  isTransitioning: boolean;
}) {
  const isInProgress = colIndex === 1;
  const meta = item.pr ?? item.priority ?? item.branch?.split("/")[1] ?? "";

  return (
    <motion.div
      layout
      layoutId={item.id}
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{
        opacity: 1,
        y: 0,
        scale: 1,
        boxShadow: isTransitioning
          ? `0 0 20px ${color}40, 0 0 40px ${color}15`
          : "0 0 0px transparent",
      }}
      exit={{ opacity: 0, y: -10, scale: 0.95 }}
      transition={{
        layout: { type: "spring", stiffness: 350, damping: 30 },
        opacity: { duration: 0.3 },
        y: { duration: 0.3 },
        scale: { duration: 0.3 },
        boxShadow: { duration: 0.5 },
      }}
      className="relative rounded-xl border border-white/[0.06] bg-[#0A0F1A] px-3.5 py-3 overflow-hidden group"
      style={{ borderLeftWidth: 3, borderLeftColor: `${color}60` }}
    >
      {/* Glow overlay during transition */}
      <AnimatePresence>
        {isTransitioning && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="absolute inset-0 rounded-xl pointer-events-none"
            style={{ background: `linear-gradient(135deg, ${color}10 0%, transparent 60%)` }}
          />
        )}
      </AnimatePresence>

      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            {isInProgress && <PulsingDot color={color} />}
            <code className="text-xs font-mono font-bold text-white/70 truncate">
              {item.id}
            </code>
          </div>
          <p className="text-[11px] text-[#8B9CC0] leading-relaxed line-clamp-2">
            {item.title}
          </p>
        </div>
      </div>

      {/* Metadata row */}
      <div className="flex items-center gap-2 mt-2 flex-wrap">
        {meta && (
          <span
            className="text-[10px] font-mono px-1.5 py-0.5 rounded-md"
            style={{ color: `${color}90`, backgroundColor: `${color}10` }}
          >
            {meta}
          </span>
        )}
        {item.ci && (
          <span className="text-[10px] font-mono text-[#34D399]/70 bg-[#34D399]/10 px-1.5 py-0.5 rounded-md">
            {item.ci}
          </span>
        )}
        {item.date && (
          <span className="text-[10px] font-mono text-white/25">
            {item.date}
          </span>
        )}
        {item.owner && (
          <span className="text-[10px] font-mono text-white/20 truncate max-w-[120px]">
            {item.owner}
          </span>
        )}
      </div>
    </motion.div>
  );
}

/* ── Column Component ── */
function KanbanColumn({
  col,
  colIndex,
  items,
  isSelected,
  onSelect,
  transitioningItemId,
}: {
  col: (typeof columns)[0];
  colIndex: number;
  items: BoardItem[];
  isSelected: boolean;
  onSelect: () => void;
  transitioningItemId: string | null;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: colIndex * 0.1, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-col min-w-0"
    >
      {/* Column Header */}
      <button
        onClick={onSelect}
        className="relative flex items-center justify-between px-3.5 py-2.5 rounded-xl mb-3 transition-all duration-300 border"
        style={{
          backgroundColor: isSelected ? `${col.color}12` : `${col.color}06`,
          borderColor: isSelected ? `${col.color}35` : `${col.color}12`,
          boxShadow: isSelected ? `0 0 16px ${col.color}15, inset 0 1px 0 ${col.color}10` : "none",
        }}
      >
        {/* Glow effect when selected */}
        {isSelected && (
          <motion.div
            layoutId="column-glow"
            className="absolute inset-0 rounded-xl pointer-events-none"
            style={{
              background: `radial-gradient(ellipse at center, ${col.color}08 0%, transparent 70%)`,
            }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
          />
        )}
        <span
          className="text-xs font-mono font-bold relative z-10 transition-colors duration-300"
          style={{ color: isSelected ? col.color : `${col.color}80` }}
        >
          {col.label}
        </span>
        <span
          className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded-md relative z-10 transition-all duration-300"
          style={{
            color: col.color,
            backgroundColor: `${col.color}15`,
            opacity: isSelected ? 1 : 0.6,
          }}
        >
          {items.length}
        </span>
      </button>

      {/* Cards */}
      <div className="flex flex-col gap-2.5 min-h-[120px]">
        <AnimatePresence mode="popLayout">
          {items.map((item) => (
            <KanbanCard
              key={item.id}
              item={item}
              colIndex={colIndex}
              color={col.color}
              isTransitioning={transitioningItemId === item.id}
            />
          ))}
        </AnimatePresence>

        {/* Empty state */}
        {items.length === 0 && (
          <div
            className="rounded-xl border border-dashed py-6 flex items-center justify-center"
            style={{ borderColor: `${col.color}15` }}
          >
            <span className="text-[10px] font-mono" style={{ color: `${col.color}30` }}>
              empty
            </span>
          </div>
        )}
      </div>
    </motion.div>
  );
}

/* ── Main KanbanSection ── */
export function KanbanSection() {
  const locale = useLocale();
  const [activeCol, setActiveCol] = useState(1);
  const [boardItems, setBoardItems] = useState(initialItems);
  const [migrationStep, setMigrationStep] = useState(0);
  const [transitioningItemId, setTransitioningItemId] = useState<string | null>(null);

  const boardRef = useRef(null);
  const boardInView = useInView(boardRef, { once: false, margin: "-100px" });

  /* ── Auto-cycling card migration ── */
  const runMigration = useCallback(() => {
    const step = migrationSequence[migrationStep % migrationSequence.length];

    setBoardItems((prev) => {
      const sourceItems = prev[step.from];
      const itemIndex = sourceItems.findIndex((i) => i.id === step.itemId);

      // If item not in source column, skip to next step
      if (itemIndex === -1) return prev;

      const item = sourceItems[itemIndex];
      setTransitioningItemId(item.id);

      const newSource = sourceItems.filter((_, idx) => idx !== itemIndex);
      const newTarget = [...prev[step.to], item];

      return {
        ...prev,
        [step.from]: newSource,
        [step.to]: newTarget,
      };
    });

    // Clear transition glow after animation
    setTimeout(() => setTransitioningItemId(null), 1200);
    setMigrationStep((s) => s + 1);
  }, [migrationStep]);

  useEffect(() => {
    if (!boardInView) return;
    const interval = setInterval(runMigration, 4000);
    return () => clearInterval(interval);
  }, [boardInView, runMigration]);

  // Reset board periodically to keep the demo looping
  useEffect(() => {
    if (migrationStep > 0 && migrationStep % migrationSequence.length === 0) {
      const timeout = setTimeout(() => {
        setBoardItems(initialItems);
      }, 3000);
      return () => clearTimeout(timeout);
    }
  }, [migrationStep]);

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      {/* Flow arrow CSS animation */}
      <style>{`
        @keyframes flow-dash {
          to { stroke-dashoffset: -12; }
        }
        .animate-flow-dash {
          animation: flow-dash 0.8s linear infinite;
        }
      `}</style>

      <div className="relative z-10 max-w-5xl mx-auto">
        {/* ── Header ── */}
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#F4B8C8]/60 uppercase tracking-[0.25em] mb-3">
            Kanban
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-3">
            Markdown Collaboration Board
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-10 leading-relaxed">
            {locale === "ko" ? (
              <><code className="text-[#F4B8C8]/60">docs/progress.md</code>를 SOT로 사람과 다수의 세션 및 에이전트가 협업합니다. Git이 트랜잭션 로그, main 브랜치가 단일 진실 소스. 30+ 세션의 작업 이력이 추적됩니다.</>
            ) : (
              <>Humans and multiple sessions/agents collaborate with <code className="text-[#F4B8C8]/60">docs/progress.md</code> as SOT. Git serves as the transaction log, main branch as single source of truth. Work history across 30+ sessions is tracked.</>
            )}
          </p>
        </ScrollReveal>

        {/* ── Animated Board ── */}
        <ScrollReveal delay={0.05}>
          <div ref={boardRef} className="relative">
            {/* Board container */}
            <div className="rounded-2xl border border-white/[0.06] bg-[#0C1220]/80 backdrop-blur-sm p-4 sm:p-5 mb-6 overflow-hidden">
              {/* Board title bar */}
              <div className="flex items-center gap-2 mb-4 pb-3 border-b border-white/[0.04]">
                <div className="flex gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#E87080]/40" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#F5C542]/40" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#34D399]/40" />
                </div>
                <code className="text-[10px] font-mono text-white/25 ml-2">docs/progress.md</code>
              </div>

              {/* Columns grid with flow arrows */}
              <div className="flex flex-col md:flex-row gap-3 md:gap-0">
                {columns.map((col, i) => (
                  <div key={col.id} className="flex items-start flex-1 min-w-0">
                    <div className="flex-1 min-w-0">
                      <KanbanColumn
                        col={col}
                        colIndex={i}
                        items={boardItems[i] || []}
                        isSelected={activeCol === i}
                        onSelect={() => setActiveCol(i)}
                        transitioningItemId={transitioningItemId}
                      />
                    </div>
                    {i < 3 && <FlowArrow />}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </ScrollReveal>

        {/* ── Stats Bar ── */}
        <ScrollReveal delay={0.08}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-10">
            {stats.map((stat, i) => (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 + i * 0.08 }}
                className="relative rounded-xl border border-white/[0.06] bg-[#0A0F1A] px-4 py-3 text-center overflow-hidden"
              >
                <div
                  className="absolute inset-0 opacity-[0.03]"
                  style={{ background: `radial-gradient(circle at center, ${stat.color} 0%, transparent 70%)` }}
                />
                <span
                  className="text-sm font-mono font-bold relative z-10"
                  style={{ color: stat.color }}
                >
                  {stat.label}
                </span>
              </motion.div>
            ))}
          </div>
        </ScrollReveal>

        {/* ── Worktree + .owner Isolation ── */}
        <ScrollReveal delay={0.1}>
          <div className="rounded-xl border border-white/[0.04] px-5 py-5 mb-6 bg-[#0C1220]/40">
            <div className="text-sm font-semibold text-white/70 mb-4">Worktree + .owner Isolation</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <div>
                <div className="text-xs text-[#8B9CC0] leading-relaxed mb-3">
                  {locale === "ko" ? (
                    <>작업마다 <code className="text-[#818CF8]/60">git worktree add</code>로 격리 환경을 할당합니다. <code className="text-[#F4B8C8]/60 ml-1">.owner</code> 파일에 세션 ID + task_id를 기록하여 타 세션이 워크트리를 삭제하는 것을 방지합니다.</>
                  ) : (
                    <>Each task gets an isolated environment via <code className="text-[#818CF8]/60">git worktree add</code>. The <code className="text-[#F4B8C8]/60 ml-1">.owner</code> file records session ID + task_id to prevent other sessions from deleting the worktree.</>
                  )}
                </div>
                <motion.div
                  initial={{ opacity: 0, y: 15 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: "-60px" }}
                  transition={{ duration: 0.6, delay: 0.1 }}
                  className="rounded-lg bg-[#060B14] px-4 py-3.5 font-mono text-xs text-white/40 leading-relaxed border border-white/[0.03]"
                >
                  <div className="text-[#7A8CA8]">$ cat .claude/worktrees/skill-2.0/.owner</div>
                  <div className="text-[#4ECDC4]/60 mt-1.5">session=2026-03-29T04:06:08+09:00</div>
                  <div className="text-[#4ECDC4]/60">task_id=skill-2.0</div>
                </motion.div>
              </div>
              <div>
                <div className="text-xs text-[#8B9CC0] leading-relaxed mb-3">
                  {t(locale,
                    "동시에 여러 워크트리를 운영하여 병렬 작업이 가능합니다. 세션 시작 시 Cross-check로 고아 워크트리(In Progress인데 워크트리 없음)를 탐지합니다.",
                    "Multiple worktrees can run simultaneously for parallel work. On session start, cross-check detects orphan worktrees (In Progress but no worktree exists)."
                  )}
                </div>
                <motion.div
                  initial={{ opacity: 0, y: 15 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: "-60px" }}
                  transition={{ duration: 0.6, delay: 0.2 }}
                  className="rounded-lg bg-[#060B14] px-4 py-3.5 font-mono text-xs text-white/40 leading-relaxed border border-white/[0.03]"
                >
                  <div className="text-[#7A8CA8]">$ git worktree list</div>
                  <div className="mt-1.5">
                    <span className="text-white/30">/workspace/geode</span>{" "}
                    <span className="text-[#34D399]/50">main</span>
                  </div>
                  <div>
                    <span className="text-white/30">.claude/worktrees/skill-2.0</span>{" "}
                    <span className="text-[#818CF8]/50">feature/skill-2.0</span>
                  </div>
                  <div>
                    <span className="text-white/30">.claude/worktrees/data-path</span>{" "}
                    <span className="text-[#818CF8]/50">feature/data-path</span>
                  </div>
                </motion.div>
              </div>
            </div>
          </div>
        </ScrollReveal>

        {/* ── Board Rules ── */}
        <ScrollReveal delay={0.12}>
          <div className="space-y-2.5">
            {rules.map((r, i) => (
              <motion.div
                key={r.ruleKo}
                initial={{ opacity: 0, x: -15 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.5, delay: i * 0.06 }}
                className="flex items-start gap-3 px-4 py-3 rounded-xl border border-white/[0.04] transition-colors duration-300 hover:border-white/[0.08]"
                style={{ background: `${r.color}03` }}
              >
                <span
                  className="shrink-0 w-2 h-2 rounded-full mt-1.5"
                  style={{ background: r.color, opacity: 0.5 }}
                />
                <div>
                  <span className="text-sm font-mono font-semibold text-white/70">{locale === "en" ? r.ruleEn : r.ruleKo}</span>
                  <p className="text-xs text-[#8B9CC0] mt-0.5 leading-relaxed">{locale === "en" ? r.descEn : r.descKo}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
