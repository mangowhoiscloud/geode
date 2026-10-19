import type { Metadata } from "next";
import { ResearchPage } from "@/components/geode/research-page";

const title = "Research | GEODE";
const description = "GEODE 기술 리포트, Jev Decision Offloading 실험, JEVDB 논문 리뷰. 원본 보고서와 발표, 실험 근거를 탐색합니다.";
const url = "https://mangowhoiscloud.github.io/geode/research/";

export const metadata: Metadata = { title, description, alternates: { canonical: url }, openGraph: { title, description, url, type: "website" } };

export default function Page() {
  return <ResearchPage />;
}
