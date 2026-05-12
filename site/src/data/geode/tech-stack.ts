export interface TechCategory {
  title: string;
  items: string[];
}

export const geodeTechCategories: TechCategory[] = [
  {
    title: "Core",
    items: ["Python 3.12", "LangGraph", "Pydantic v2", "TypedDict"],
  },
  {
    title: "LLM",
    items: ["Claude Opus", "Anthropic SDK", "Structured Output", "JSON Mode"],
  },
  {
    title: "CLI / UI",
    items: ["Typer", "Rich", "Rich Live", "Rich Panel"],
  },
  {
    title: "Testing",
    items: ["pytest", "pytest-asyncio", "unittest.mock", "98 tests"],
  },
  {
    title: "Quality",
    items: ["mypy", "ruff", "Type Hints", "Strict Mode"],
  },
  {
    title: "Architecture",
    items: ["Port/Adapter", "Factory", "DI", "Clean Architecture"],
  },
];
