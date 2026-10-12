import type { Metadata } from "next";
import { ReportReader } from "@/components/geode/report-reader";

const title = "GEODE 기술 리포트 | 실행·상태·평가·실험";
const description = "GEODE 공개 기술 리포트의 한·영 92쪽을 장면별로 읽습니다. 원본 도표, 측정 조건, PDF와 추출 본문을 보존한 웹 reader.";
const url = "https://mangowhoiscloud.github.io/geode/research/geode/";

export const metadata: Metadata = { title, description, alternates: { canonical: url }, openGraph: { title, description, url, type: "article" } };

export default function Page() {
  return <ReportReader />;
}
