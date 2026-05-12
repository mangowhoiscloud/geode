import { Node, Edge } from "@xyflow/react";

// Pipeline node definitions for GEODE's LangGraph StateGraph
// Topology: START → router → signals → analyst×4 (fan-out) → evaluators×3 → scoring → verification → synthesizer → END
// Loopback: verification → gather → signals (if confidence < 0.7, max 5)

export const pipelineNodes: Node[] = [
  { id: "start", type: "geodeStart", position: { x: 0, y: 180 }, data: { label: "START", delay: 0 } },

  { id: "router", type: "geodeStage", position: { x: 120, y: 168 }, data: {
    icon: "🗺️", label: "Router", description: "Memory context", color: "indigo", delay: 0.05,
  }},

  { id: "signals", type: "geodeStage", position: { x: 280, y: 168 }, data: {
    icon: "📡", label: "Signals", description: "MCP sources", color: "cyan", delay: 0.1,
  }},

  // 4 Analysts (fan-out via Send API, clean context)
  { id: "analyst-market", type: "geodeAnalyst", position: { x: 440, y: 20 }, data: {
    icon: "📊", label: "Market", description: "시장 규모·성장률", axis: "A-C", delay: 0.15,
  }},
  { id: "analyst-creative", type: "geodeAnalyst", position: { x: 440, y: 110 }, data: {
    icon: "🎨", label: "Creative", description: "IP 창작 잠재력", axis: "D-F", delay: 0.2,
  }},
  { id: "analyst-audience", type: "geodeAnalyst", position: { x: 440, y: 200 }, data: {
    icon: "👥", label: "Audience", description: "팬덤·커뮤니티", axis: "G-I", delay: 0.25,
  }},
  { id: "analyst-risk", type: "geodeAnalyst", position: { x: 440, y: 290 }, data: {
    icon: "⚠️", label: "Risk", description: "리스크 평가", axis: "J-L", delay: 0.3,
  }},

  // Evaluators ×3
  { id: "evaluators", type: "geodeStage", position: { x: 620, y: 168 }, data: {
    icon: "⚖️", label: "Eval ×3", description: "Cross-check", color: "amber", delay: 0.35,
  }},

  // Scoring (PSM)
  { id: "scoring", type: "geodeStage", position: { x: 770, y: 168 }, data: {
    icon: "🎯", label: "Scoring", description: "PSM composite", color: "emerald", delay: 0.4,
  }},

  // Verification (6-layer)
  { id: "verification", type: "geodeStage", position: { x: 920, y: 168 }, data: {
    icon: "🛡️", label: "Verify", description: "6-layer trust", color: "yellow", delay: 0.45,
  }},

  // Synthesizer
  { id: "synthesizer", type: "geodeStage", position: { x: 1070, y: 168 }, data: {
    icon: "📝", label: "Synth", description: "Report", color: "purple", delay: 0.5,
  }},

  { id: "end", type: "geodeEnd", position: { x: 1200, y: 180 }, data: { label: "END", delay: 0.55 } },
];

export const pipelineEdges: Edge[] = [
  // Main flow
  { id: "e-start-router", source: "start", target: "router", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },
  { id: "e-router-signals", source: "router", target: "signals", animated: true, style: { stroke: "#60A5FA", strokeWidth: 2 } },

  // Fan-out: signals → analysts (Send API)
  { id: "e-signals-market", source: "signals", target: "analyst-market", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 }, label: "Send API" },
  { id: "e-signals-creative", source: "signals", target: "analyst-creative", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },
  { id: "e-signals-audience", source: "signals", target: "analyst-audience", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },
  { id: "e-signals-risk", source: "signals", target: "analyst-risk", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },

  // Fan-in: analysts → evaluators
  { id: "e-market-eval", source: "analyst-market", target: "evaluators", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },
  { id: "e-creative-eval", source: "analyst-creative", target: "evaluators", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },
  { id: "e-audience-eval", source: "analyst-audience", target: "evaluators", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },
  { id: "e-risk-eval", source: "analyst-risk", target: "evaluators", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },

  // Post-eval flow
  { id: "e-eval-scoring", source: "evaluators", target: "scoring", animated: true, style: { stroke: "#34D399", strokeWidth: 2 } },
  { id: "e-scoring-verif", source: "scoring", target: "verification", animated: true, style: { stroke: "#FBBF24", strokeWidth: 2 } },
  { id: "e-verif-synth", source: "verification", target: "synthesizer", animated: true, style: { stroke: "#A78BFA", strokeWidth: 2 } },
  { id: "e-synth-end", source: "synthesizer", target: "end", animated: true, style: { stroke: "#818CF8", strokeWidth: 2 } },

  // Confidence loopback: verification → signals (gather node implicit)
  {
    id: "e-loopback",
    source: "verification",
    target: "signals",
    type: "smoothstep",
    style: { stroke: "#E87080", strokeWidth: 1.5, strokeDasharray: "6,4" },
    label: "confidence < 0.7",
    animated: false,
  },
];
