import { Node, Edge } from "@xyflow/react";

// Runtime node definitions for GEODE's AgenticLoop.
// Topology: START → context → prompt → model → tool execution → context guard → answer → END
// Loopback: tool execution → model while the model keeps emitting tool_use.

export const pipelineNodes: Node[] = [
  { id: "start", type: "geodeStart", position: { x: 0, y: 180 }, data: { label: "START", delay: 0 } },

  { id: "router", type: "geodeStage", position: { x: 120, y: 168 }, data: {
    icon: "🧠", label: "Context", description: "5-tier merge", color: "indigo", delay: 0.05,
  }},

  { id: "signals", type: "geodeStage", position: { x: 280, y: 168 }, data: {
    icon: "🧩", label: "Prompt", description: "static + dynamic", color: "cyan", delay: 0.1,
  }},

  // Model/tool loop surfaces
  { id: "analyst-market", type: "geodeAnalyst", position: { x: 440, y: 20 }, data: {
    icon: "🤖", label: "Model", description: "tool_use 판단", axis: "LLM", delay: 0.15,
  }},
  { id: "analyst-creative", type: "geodeAnalyst", position: { x: 440, y: 110 }, data: {
    icon: "🛠️", label: "Tools", description: "실행 + 승인", axis: "Exec", delay: 0.2,
  }},
  { id: "analyst-audience", type: "geodeAnalyst", position: { x: 440, y: 200 }, data: {
    icon: "📦", label: "Offload", description: "큰 결과 저장", axis: "ref_id", delay: 0.25,
  }},
  { id: "analyst-risk", type: "geodeAnalyst", position: { x: 440, y: 290 }, data: {
    icon: "👥", label: "SubAgent", description: "격리 위임", axis: "toolkit", delay: 0.3,
  }},

  { id: "evaluators", type: "geodeStage", position: { x: 620, y: 168 }, data: {
    icon: "🪟", label: "Window", description: "80/95% guard", color: "amber", delay: 0.35,
  }},

  { id: "scoring", type: "geodeStage", position: { x: 770, y: 168 }, data: {
    icon: "🪝", label: "Hooks", description: "overflow action", color: "emerald", delay: 0.4,
  }},

  { id: "verification", type: "geodeStage", position: { x: 920, y: 168 }, data: {
    icon: "💉", label: "Reminder", description: "append-only", color: "yellow", delay: 0.45,
  }},

  { id: "synthesizer", type: "geodeStage", position: { x: 1070, y: 168 }, data: {
    icon: "📝", label: "Answer", description: "termination reason", color: "purple", delay: 0.5,
  }},

  { id: "end", type: "geodeEnd", position: { x: 1200, y: 180 }, data: { label: "END", delay: 0.55 } },
];

export const pipelineEdges: Edge[] = [
  // Main flow
  { id: "e-start-router", source: "start", target: "router", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },
  { id: "e-router-signals", source: "router", target: "signals", animated: true, style: { stroke: "#60A5FA", strokeWidth: 2 } },

  // Prompt → runtime surfaces
  { id: "e-signals-market", source: "signals", target: "analyst-market", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 }, label: "call" },
  { id: "e-signals-creative", source: "signals", target: "analyst-creative", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },
  { id: "e-signals-audience", source: "signals", target: "analyst-audience", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },
  { id: "e-signals-risk", source: "signals", target: "analyst-risk", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },

  // Runtime surfaces → context window guard
  { id: "e-market-eval", source: "analyst-market", target: "evaluators", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },
  { id: "e-creative-eval", source: "analyst-creative", target: "evaluators", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },
  { id: "e-audience-eval", source: "analyst-audience", target: "evaluators", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },
  { id: "e-risk-eval", source: "analyst-risk", target: "evaluators", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },

  // Post-guard flow
  { id: "e-eval-scoring", source: "evaluators", target: "scoring", animated: true, style: { stroke: "#34D399", strokeWidth: 2 } },
  { id: "e-scoring-verif", source: "scoring", target: "verification", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },
  { id: "e-verif-synth", source: "verification", target: "synthesizer", animated: true, style: { stroke: "#A78BFA", strokeWidth: 2 } },
  { id: "e-synth-end", source: "synthesizer", target: "end", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },

  // Agentic loopback: model emits more tool_use
  {
    id: "e-loopback",
    source: "analyst-creative",
    target: "analyst-market",
    type: "smoothstep",
    style: { stroke: "#E87080", strokeWidth: 1.5, strokeDasharray: "6,4" },
    label: "while tool_use",
    animated: false,
  },
];
