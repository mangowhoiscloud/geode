"use client";

import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  Position,
  Handle,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion } from "framer-motion";
import {
  agenticLoopNodes,
  agenticLoopEdges,
} from "@/data/geode/agentic-loop-nodes";

/* ---------- Color Map ---------- */
const colorMap: Record<string, { bg: string; border: string; text: string; glow: string }> = {
  blue: {
    bg: "from-blue-500/25 to-blue-600/15",
    border: "border-blue-400",
    text: "text-blue-200",
    glow: "shadow-blue-500/20",
  },
  pink: {
    bg: "from-pink-500/25 to-pink-600/15",
    border: "border-pink-400",
    text: "text-pink-200",
    glow: "shadow-pink-500/20",
  },
  amber: {
    bg: "from-amber-500/25 to-amber-600/15",
    border: "border-amber-400",
    text: "text-amber-200",
    glow: "shadow-amber-500/20",
  },
  emerald: {
    bg: "from-emerald-500/25 to-emerald-600/15",
    border: "border-emerald-400",
    text: "text-emerald-200",
    glow: "shadow-emerald-500/20",
  },
  slate: {
    bg: "from-slate-500/25 to-slate-600/15",
    border: "border-slate-400",
    text: "text-slate-200",
    glow: "shadow-slate-500/20",
  },
};

/* ---------- Entry Node (USER) ---------- */
function LoopEntryNode({ data }: { data: Record<string, unknown> }) {
  const colors = colorMap[(data.color as string) || "slate"];
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay: (data.delay as number) || 0 }}
      className={`w-16 h-16 rounded-full bg-gradient-to-br ${colors.bg} border-2 ${colors.border} flex items-center justify-center shadow-lg ${colors.glow}`}
    >
      <div className="text-center">
        <div className="text-xl">{data.icon as string}</div>
        <div className="text-[8px] font-bold text-slate-300 mt-0.5">{data.label as string}</div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-slate-400 !w-2.5 !h-2.5" />
    </motion.div>
  );
}

/* ---------- Core Node (THINK — the hub of the loop) ---------- */
function LoopCoreNode({ data }: { data: Record<string, unknown> }) {
  const colors = colorMap[(data.color as string) || "blue"];
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay: (data.delay as number) || 0 }}
      className={`px-5 py-4 rounded-2xl bg-gradient-to-br ${colors.bg} border-2 ${colors.border} min-w-[130px] backdrop-blur-sm shadow-lg ${colors.glow} relative`}
    >
      {/* Handles */}
      <Handle type="target" position={Position.Left} id="think-left" className="!bg-blue-400 !w-3 !h-3" />
      <Handle type="source" position={Position.Right} id="think-right" className="!bg-blue-400 !w-3 !h-3" />
      <Handle type="source" position={Position.Bottom} id="think-bottom-source" className="!bg-emerald-400 !w-2.5 !h-2.5" />
      <Handle type="target" position={Position.Bottom} id="think-bottom-target" className="!bg-pink-400 !w-2.5 !h-2.5" />
      <div className="text-center">
        <div className="text-2xl mb-1">{data.icon as string}</div>
        <div className="font-bold text-white text-sm">{data.label as string}</div>
        <div className={`text-[10px] ${colors.text} mt-0.5`}>{data.description as string}</div>
      </div>
      {/* Loop badge */}
      <div className="absolute -top-2 -right-2 px-1.5 py-0.5 bg-amber-500/90 rounded-full text-[7px] font-bold text-black">
        max_rounds=50
      </div>
    </motion.div>
  );
}

/* ---------- Stage Node (SELECT, EXECUTE, VERIFY) ---------- */
function LoopStageNode({ data }: { data: Record<string, unknown> }) {
  const colors = colorMap[(data.color as string) || "amber"];
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay: (data.delay as number) || 0 }}
      className={`px-4 py-3 rounded-xl bg-gradient-to-br ${colors.bg} border-2 ${colors.border} min-w-[120px] backdrop-blur-sm shadow-lg ${colors.glow}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-white/50 !w-2.5 !h-2.5" />
      <Handle type="target" position={Position.Left} id="stage-left-target" className="!bg-white/50 !w-2.5 !h-2.5" />
      <Handle type="source" position={Position.Bottom} className="!bg-white/50 !w-2.5 !h-2.5" />
      <Handle type="source" position={Position.Right} id="stage-right-source" className="!bg-white/50 !w-2.5 !h-2.5" />
      <Handle type="source" position={Position.Left} id="stage-left-source" className="!bg-white/50 !w-2.5 !h-2.5" />
      <div className="text-center">
        <div className="text-xl mb-0.5">{data.icon as string}</div>
        <div className="font-bold text-white text-xs">{data.label as string}</div>
        <div className={`text-[9px] ${colors.text} mt-0.5`}>{data.description as string}</div>
      </div>
    </motion.div>
  );
}

/* ---------- End Node (FINALIZE) ---------- */
function LoopEndNode({ data }: { data: Record<string, unknown> }) {
  const colors = colorMap[(data.color as string) || "emerald"];
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay: (data.delay as number) || 0 }}
      className={`px-5 py-4 rounded-2xl bg-gradient-to-br ${colors.bg} border-2 ${colors.border} min-w-[110px] backdrop-blur-sm shadow-lg ${colors.glow}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-emerald-400 !w-3 !h-3" />
      <Handle type="target" position={Position.Top} id="end-top-target" className="!bg-emerald-400 !w-2.5 !h-2.5" />
      <div className="text-center">
        <div className="text-2xl mb-1">{data.icon as string}</div>
        <div className="font-bold text-white text-sm">{data.label as string}</div>
        <div className={`text-[9px] ${colors.text} mt-0.5`}>{data.description as string}</div>
      </div>
    </motion.div>
  );
}

/* ---------- Node Type Registry ---------- */
const nodeTypes = {
  loopEntry: LoopEntryNode,
  loopCore: LoopCoreNode,
  loopStage: LoopStageNode,
  loopEnd: LoopEndNode,
};

/* ---------- Stats Bar ---------- */
function StatsBar() {
  return (
    <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ delay: 0.7, duration: 0.4 }}
      className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex items-center gap-3 px-5 py-2 rounded-full bg-white/5 border border-white/10 backdrop-blur-md"
    >
      {[
        { value: "46", label: "Tools" },
        { value: "43", label: "MCP" },
        { value: "3", label: "Providers" },
        { value: "50", label: "max_rounds" },
      ].map((stat) => (
        <div key={stat.label} className="flex items-center gap-1.5">
          <span className="text-white font-bold text-xs font-[family-name:var(--font-geist-mono)]">
            {stat.value}
          </span>
          <span className="text-white/50 text-[10px]">{stat.label}</span>
        </div>
      ))}
    </motion.div>
  );
}

/* ---------- Main Diagram ---------- */
export function AgenticLoopDiagram() {
  const [nodes, , onNodesChange] = useNodesState(agenticLoopNodes);
  const [edges, , onEdgesChange] = useEdgesState(agenticLoopEdges);

  return (
    <div className="relative w-full h-full min-h-[420px] rounded-xl overflow-hidden border border-white/10 bg-[#0a0a12]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={1.5}
        attributionPosition="bottom-left"
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#1a1a2e" />
        <Controls className="!bg-[#1a1a2e] !border-white/10 !rounded-lg" />
      </ReactFlow>
      <StatsBar />
    </div>
  );
}

export default AgenticLoopDiagram;
