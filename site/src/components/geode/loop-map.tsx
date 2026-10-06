import Link from "next/link";
import { t, type Locale } from "@/components/geode/locale-context";
import "./loop-map.css";

/** A conceptual map, not a live run or a claim of automatic promotion. */
export function LoopMap({ locale }: { locale: Locale }) {
  return (
    <figure className="geode-loop-map" aria-label={t(locale, "GEODE의 런타임과 실험 루프", "GEODE runtime and experimental loop")}>
      <div className="loop-map-runtime">
        <p className="loop-map-label">Autonomous Agent Harness</p>
        <h3>{t(locale, "지금 맡긴 작업을 수행합니다", "Run the task at hand")}</h3>
        <ol className="loop-map-cycle">
          <li>{t(locale, "판단", "Decide")}</li><li>{t(locale, "도구 실행", "Act")}</li><li>{t(locale, "관측", "Observe")}</li>
        </ol>
        <p className="loop-map-return">↶ {t(locale, "관측을 읽고 다음 행동을 선택", "Use observations to choose the next action")}</p>
      </div>
      <div className="loop-map-bridge">
        <span aria-hidden="true">↓</span>
        <p>{t(locale, "실행 기록을 측정과 탐색의 근거로", "Execution records inform evaluation and search")}</p>
      </div>
      <div className="loop-map-experiment">
        <p className="loop-map-label">Experimental Loop</p>
        <h3>{t(locale, "다음 실행에 쓸 후보를 검증합니다", "Test candidates for future runs")}</h3>
        <ol className="loop-map-cycle">
          <li>{t(locale, "후보 생성", "Propose")}</li><li>{t(locale, "평가", "Evaluate")}</li><li>{t(locale, "채택·복원", "Keep / revert")}</li>
        </ol>
        <p className="loop-map-return">{t(locale, "탐색 중 채택 ≠ 독립 검증 ≠ 배포", "Search acceptance ≠ independent validation ≠ release")}</p>
      </div>
      <figcaption>
        {t(locale, "구현 구조의 개념도. 지속적 성능 향상은 별도 검증 대상입니다.", "Conceptual architecture. Sustained improvement requires separate evidence.")}{" "}
        <Link href={`/docs/research/overview?lang=${locale}`}>{t(locale, "연구와 근거", "Research and evidence")}</Link>
      </figcaption>
    </figure>
  );
}
