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
import { pipelineNodes, pipelineEdges } from "@/data/geode/pipeline-nodes";

const colorMap: Record<string, { bg: string; border: string; text: string }> = {
  indigo: { bg: "from-indigo-500/25 to-indigo-600/15", border: "border-indigo-400", text: "text-indigo-200" },
  blue: { bg: "from-blue-500/25 to-blue-600/15", border: "border-blue-400", text: "text-blue-200" },
  cyan: { bg: "from-cyan-500/25 to-cyan-600/15", border: "border-cyan-400", text: "text-cyan-200" },
  amber: { bg: "from-amber-500/25 to-amber-600/15", border: "border-amber-400", text: "text-amber-200" },
  emerald: { bg: "from-emerald-500/25 to-emerald-600/15", border: "border-emerald-400", text: "text-emerald-200" },
  yellow: { bg: "from-yellow-500/25 to-yellow-600/15", border: "border-yellow-400", text: "text-yellow-200" },
  purple: { bg: "from-purple-500/25 to-purple-600/15", border: "border-purple-400", text: "text-purple-200" },
};

// Stage Node (main pipeline nodes)
function GeodeStageNode({ data }: { data: Record<string, unknown> }) {
  const colors = colorMap[(data.color as string) || "indigo"];
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay: (data.delay as number) || 0 }}
      className={`px-4 py-3 rounded-xl bg-gradient-to-br ${colors.bg} border-2 ${colors.border} min-w-[110px] backdrop-blur-sm`}
    >
      <Handle type="target" position={Position.Left} className="!bg-white/50 !w-2.5 !h-2.5" />
      <div className="text-center">
        <div className="text-xl mb-0.5">{data.icon as string}</div>
        <div className="font-bold text-white text-xs">{data.label as string}</div>
        <div className={`text-[9px] ${colors.text} mt-0.5`}>{data.description as string}</div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-white/50 !w-2.5 !h-2.5" />
    </motion.div>
  );
}

// Analyst Node (fan-out nodes)
function GeodeAnalystNode({ data }: { data: Record<string, unknown> }) {
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay: (data.delay as number) || 0 }}
      className="px-3 py-2.5 rounded-lg bg-gradient-to-br from-indigo-500/20 to-violet-600/10 border border-indigo-400/60 min-w-[100px] backdrop-blur-sm"
    >
      <Handle type="target" position={Position.Left} className="!bg-indigo-300/50 !w-2 !h-2" />
      <div className="text-center">
        <div className="text-lg mb-0.5">{data.icon as string}</div>
        <div className="font-semibold text-white text-[10px]">{data.label as string}</div>
        <div className="text-[8px] text-indigo-200/80">{data.description as string}</div>
        <div className="mt-1 px-1.5 py-0.5 bg-white/10 rounded text-[7px] text-white/70">
          {data.axis as string}
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-indigo-300/50 !w-2 !h-2" />
    </motion.div>
  );
}

// Start Node
function GeodeStartNode({ data }: { data: Record<string, unknown> }) {
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay: (data.delay as number) || 0 }}
      className="w-14 h-14 rounded-full bg-gradient-to-br from-indigo-500/30 to-indigo-600/20 border-2 border-indigo-400 flex items-center justify-center shadow-lg shadow-indigo-500/20"
    >
      <span className="text-xs font-bold text-indigo-300">{data.label as string}</span>
      <Handle type="source" position={Position.Right} className="!bg-indigo-400 !w-2.5 !h-2.5" />
    </motion.div>
  );
}

// End Node
function GeodeEndNode({ data }: { data: Record<string, unknown> }) {
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay: (data.delay as number) || 0 }}
      className="w-14 h-14 rounded-full bg-gradient-to-br from-emerald-500/30 to-emerald-600/20 border-2 border-emerald-400 flex items-center justify-center shadow-lg shadow-emerald-500/20"
    >
      <Handle type="target" position={Position.Left} className="!bg-emerald-400 !w-2.5 !h-2.5" />
      <span className="text-xs font-bold text-emerald-300">{data.label as string}</span>
    </motion.div>
  );
}

const nodeTypes = {
  geodeStage: GeodeStageNode,
  geodeAnalyst: GeodeAnalystNode,
  geodeStart: GeodeStartNode,
  geodeEnd: GeodeEndNode,
};

export function GeodePipelineDiagram() {
  const [nodes, , onNodesChange] = useNodesState(pipelineNodes);
  const [edges, , onEdgesChange] = useEdgesState(pipelineEdges);

  return (
    <div className="w-full h-[420px] rounded-xl overflow-hidden border border-white/10 bg-[#0a0a12]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.3}
        maxZoom={1.5}
        attributionPosition="bottom-left"
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#1a1a2e" />
        <Controls className="!bg-[#1a1a2e] !border-white/10 !rounded-lg" />
      </ReactFlow>
    </div>
  );
}
