export interface TechCategory {
  title: string;
  items: string[];
}

/**
 * GEODE tech stack — verified against the repo on 2026-07-10.
 * pytest count from `pytest --co` on the same date; keep values measured,
 * never aspirational.
 */
export const geodeTechCategories: TechCategory[] = [
  {
    title: "Runtime",
    items: ["Python 3.12", "AgenticLoop (while tool_use)", "Pydantic v2", "Typer", "Rich"],
  },
  {
    title: "Providers",
    items: ["Anthropic", "OpenAI / Codex", "GLM", "OAuth subscription routing"],
  },
  {
    title: "Surfaces",
    items: ["CLI", "MCP server", "Slack", "cron scheduler", "Gateway daemon"],
  },
  {
    title: "Evolving",
    items: ["Petri (inspect_ai)", "tau2-bench", "seed generation", "campaign gate"],
  },
  {
    title: "Quality",
    items: ["pytest 9,479", "mypy", "ruff", "import-linter"],
  },
  {
    title: "Site",
    items: ["Next.js 16", "React 19", "Tailwind 4", "Astryx", "Galmuri11"],
  },
];
