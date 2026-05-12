import { Node, Edge } from "@xyflow/react";

// AgenticLoop node definitions for GEODE's while(tool_use) autonomous agent loop
// Topology: USER -> THINK -> SELECT -> EXECUTE -> THINK (loop)
//                   THINK -> FINALIZE (shortcut if no tool needed)
//           EXECUTE -> VERIFY -> FINALIZE (confidence >= 0.7)
//                      VERIFY -> THINK (retry with failover if confidence < 0.7)

export const agenticLoopNodes: Node[] = [
  // USER — entry point, left side
  {
    id: "user",
    type: "loopEntry",
    position: { x: 0, y: 190 },
    data: {
      icon: "👤",
      label: "USER",
      description: "Natural language input",
      color: "slate",
      delay: 0,
    },
  },

  // THINK — LLM reasoning, top center
  {
    id: "think",
    type: "loopCore",
    position: { x: 280, y: 30 },
    data: {
      icon: "🧠",
      label: "THINK",
      description: "LLM reasoning · tool_choice?",
      color: "blue",
      delay: 0.1,
    },
  },

  // SELECT — tool selection, right side
  {
    id: "select",
    type: "loopStage",
    position: { x: 560, y: 120 },
    data: {
      icon: "🔧",
      label: "SELECT",
      description: "Pick from 43 tools",
      color: "pink",
      delay: 0.2,
    },
  },

  // EXECUTE — tool runs, bottom right
  {
    id: "execute",
    type: "loopStage",
    position: { x: 560, y: 280 },
    data: {
      icon: "⚡",
      label: "EXECUTE",
      description: "Tool runs · result → LLM",
      color: "amber",
      delay: 0.3,
    },
  },

  // VERIFY — confidence check, bottom center
  {
    id: "verify",
    type: "loopStage",
    position: { x: 280, y: 350 },
    data: {
      icon: "🛡️",
      label: "VERIFY",
      description: "Confidence check",
      color: "emerald",
      delay: 0.4,
    },
  },

  // FINALIZE — result output, far right
  {
    id: "finalize",
    type: "loopEnd",
    position: { x: 780, y: 190 },
    data: {
      icon: "✅",
      label: "FINALIZE",
      description: "Result output",
      color: "emerald",
      delay: 0.5,
    },
  },
];

export const agenticLoopEdges: Edge[] = [
  // USER → THINK (left handle)
  {
    id: "e-user-think",
    source: "user",
    target: "think",
    targetHandle: "think-left",
    animated: true,
    style: { stroke: "#94A3B8", strokeWidth: 2 },
  },

  // THINK → SELECT (if tool_use)
  {
    id: "e-think-select",
    source: "think",
    sourceHandle: "think-right",
    target: "select",
    animated: true,
    style: { stroke: "#60A5FA", strokeWidth: 2 },
    label: "tool_use",
    labelStyle: { fill: "#60A5FA", fontSize: 10, fontFamily: "var(--font-geist-mono)" },
    labelBgStyle: { fill: "#0a0a12", fillOpacity: 0.8 },
    labelBgPadding: [4, 2] as [number, number],
  },

  // THINK → FINALIZE (no tool needed — shortcut, bottom-source to end top)
  {
    id: "e-think-finalize",
    source: "think",
    sourceHandle: "think-bottom-source",
    target: "finalize",
    targetHandle: "end-top-target",
    animated: false,
    style: { stroke: "#34D399", strokeWidth: 1.5, strokeDasharray: "6,4" },
    label: "no tool needed",
    labelStyle: { fill: "#34D399", fontSize: 9, fontFamily: "var(--font-geist-mono)" },
    labelBgStyle: { fill: "#0a0a12", fillOpacity: 0.8 },
    labelBgPadding: [4, 2] as [number, number],
  },

  // SELECT → EXECUTE
  {
    id: "e-select-execute",
    source: "select",
    target: "execute",
    animated: true,
    style: { stroke: "#F4B8C8", strokeWidth: 2 },
  },

  // EXECUTE → THINK — THE LOOP (animated, dashed)
  {
    id: "e-execute-think",
    source: "execute",
    sourceHandle: "stage-left-source",
    target: "think",
    targetHandle: "think-bottom-target",
    animated: true,
    style: { stroke: "#F5C542", strokeWidth: 2.5, strokeDasharray: "8,4" },
    label: "while(tool_use)",
    labelStyle: { fill: "#F5C542", fontSize: 11, fontWeight: 700, fontFamily: "var(--font-geist-mono)" },
    labelBgStyle: { fill: "#0a0a12", fillOpacity: 0.9 },
    labelBgPadding: [6, 3] as [number, number],
  },

  // EXECUTE → VERIFY
  {
    id: "e-execute-verify",
    source: "execute",
    target: "verify",
    animated: true,
    style: { stroke: "#FBBF24", strokeWidth: 2 },
  },

  // VERIFY → FINALIZE (confidence >= 0.7)
  {
    id: "e-verify-finalize",
    source: "verify",
    sourceHandle: "stage-right-source",
    target: "finalize",
    animated: true,
    style: { stroke: "#34D399", strokeWidth: 2 },
    label: "confidence >= 0.7",
    labelStyle: { fill: "#34D399", fontSize: 9, fontFamily: "var(--font-geist-mono)" },
    labelBgStyle: { fill: "#0a0a12", fillOpacity: 0.8 },
    labelBgPadding: [4, 2] as [number, number],
  },

  // VERIFY → THINK (retry with failover)
  {
    id: "e-verify-think",
    source: "verify",
    sourceHandle: "stage-left-source",
    target: "think",
    targetHandle: "think-left",
    animated: true,
    style: { stroke: "#F472B6", strokeWidth: 1.5, strokeDasharray: "5,5" },
    label: "retry + failover",
    labelStyle: { fill: "#F472B6", fontSize: 9, fontFamily: "var(--font-geist-mono)" },
    labelBgStyle: { fill: "#0a0a12", fillOpacity: 0.8 },
    labelBgPadding: [4, 2] as [number, number],
  },
];
