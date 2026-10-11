import type { Metadata } from "next";
import { JevdbReview } from "@/components/geode/jevdb-review";

const title = "JEVDB 논문 리뷰 | Prune First, Decide Fast";
const description = "후보 축소, typed decision, 재사용과 LLM escalation으로 읽는 JEVDB. 류지환의 논문 리뷰 영상과 v25 발표 자료, 성능 비교 조건과 남은 질문.";
const url = "https://mangowhoiscloud.github.io/geode/research/jevdb/";

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: url },
  openGraph: { title, description, url, type: "article" },
};

export default function Page() {
  return <JevdbReview />;
}
