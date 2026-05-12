export interface HeroStatData {
  value: string;
  labelKo: string;
  labelEn: string;
  href?: string;
}

export const geodeStats: HeroStatData[] = [
  {
    value: "4",
    labelKo: "아키텍처 레이어",
    labelEn: "Architecture Layers",
  },
  {
    value: "8",
    labelKo: "파이프라인 노드",
    labelEn: "Pipeline Nodes",
  },
  {
    value: "4",
    labelKo: "병렬 분석가",
    labelEn: "Parallel Analysts",
  },
  {
    value: "14",
    labelKo: "루브릭 축",
    labelEn: "Rubric Axes",
  },
  {
    value: "3",
    labelKo: "평가자",
    labelEn: "Evaluators",
  },
  {
    value: "98",
    labelKo: "테스트 통과",
    labelEn: "Tests Passing",
  },
];
