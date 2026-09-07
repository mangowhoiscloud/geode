"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { Check, Terminal } from "lucide-react";
import { t, useLocale } from "@/components/geode/locale-context";
import evidence from "@/data/geode/landing-evidence.json";

/** An inspector of admitted event metadata, not a recreation of the CLI. */
export function RecordedRun() {
  const locale = useLocale();
  const run = evidence.astra;
  const calls = run.trace.events.filter((event) => event.kind === "tool.called");

  return (
    <section id="run" className="landing-record" aria-labelledby="record-title" tabIndex={-1}>
      <div className="landing-record-header">
        <span>{t(locale, "공개 실행 기록", "Recorded public run")}</span>
        <time dateTime="2026-09-04">2026-09-04</time>
      </div>
      <div className="landing-record-body">
        <h2 id="record-title">{t(locale, "TLS 인증서 생성", "Create a TLS certificate")}</h2>
        <p className="landing-record-task">{run.task}</p>
        <p className="landing-record-scope">
          GPT-6 Astra / {run.reasoning}
          <span>{t(locale, "한 작업, 한 번의 실행", "One task, one trial")}</span>
        </p>
        <Tabs.Root defaultValue="tools" className="landing-record-tabs">
          <Tabs.List aria-label={t(locale, "실행 기록 살펴보기", "Inspect the recorded run")}>
            <Tabs.Trigger value="task">{t(locale, "조건", "Setup")}</Tabs.Trigger>
            <Tabs.Trigger value="tools">{t(locale, "도구 호출", "Tool calls")}</Tabs.Trigger>
            <Tabs.Trigger value="result">{t(locale, "검증 결과", "Result")}</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="task" className="landing-record-panel">
            <dl className="landing-record-facts">
              <div><dt>{t(locale, "런타임", "Runtime")}</dt><dd>GEODE {run.geodeVersion}</dd></div>
              <div><dt>{t(locale, "모델 경로", "Model route")}</dt><dd>{run.route}</dd></div>
              <div><dt>{t(locale, "실행 기반", "Harness")}</dt><dd>{run.harness}</dd></div>
              <div><dt>{t(locale, "벤치마크", "Benchmark")}</dt><dd>Terminal-Bench 2.1</dd></div>
            </dl>
            <a className="landing-text-link" href={run.sources.spec.url}>
              {t(locale, "고정된 실행 조건", "Frozen run specification")}
            </a>
          </Tabs.Content>
          <Tabs.Content value="tools" className="landing-record-panel">
            <ol className="landing-call-list">
              {calls.map((call) => {
                const result = run.trace.events.find(
                  (event) => event.kind === "tool.completed" && event.callId === call.callId,
                );
                return (
                  <li key={call.callId}>
                    <Terminal size={18} aria-hidden="true" />
                    <div>
                      <strong>{call.tool}</strong>
                      <span>{call.occurredAt.slice(11, 19)} UTC</span>
                    </div>
                    <span className="landing-call-status">
                      <Check size={15} aria-hidden="true" /> {result?.status}
                    </span>
                  </li>
                );
              })}
            </ol>
            <p className="landing-record-note">
              {t(locale,
                `${run.toolCalls}개 호출과 ${run.toolResults}개 결과가 연결됩니다. 명령과 결과 본문은 비공개입니다.`,
                `${run.toolCalls} calls matched to ${run.toolResults} results. Command and result bodies are withheld.`,
              )}
            </p>
          </Tabs.Content>
          <Tabs.Content value="result" className="landing-record-panel">
            <div className="landing-verifier-result">
              <span>{run.verifierPassed}<span> / {run.verifierTotal}</span></span>
              <div>
                <strong>{t(locale, "verifier 검사 통과", "verifier checks passed")}</strong>
                <p>{t(locale, "Harbor의 외부 판정", "External judgement by Harbor")}</p>
              </div>
            </div>
            <p className="landing-record-note">
              {t(locale,
                `Reward ${run.passedTrials}/${run.selectedTrials}. 재시도 ${run.retries}회, fallback ${run.fallbacks}회. 계정 단위 smoke이며 전체 suite 점수가 아닙니다.`,
                `Reward ${run.passedTrials}/${run.selectedTrials}. ${run.retries} retries, ${run.fallbacks} fallbacks. Account-scoped smoke, not a suite score.`,
              )}
            </p>
            <a className="landing-text-link" href={run.sources.verifier.url}>
              {t(locale, "verifier 원본 확인", "Inspect the verifier receipt")}
            </a>
          </Tabs.Content>
        </Tabs.Root>
      </div>
      <div className="landing-record-footer">
        <span>{run.rounds} {t(locale, "라운드", "rounds")}</span>
        <span>{run.trace.eventCount} {t(locale, "공개 이벤트", "public events")}</span>
        <a href={run.sources.trajectory.url}>{t(locale, "Trajectory 원본", "Raw trajectory")}</a>
      </div>
      <p className="landing-record-disclosure">
        {t(locale,
          `공개 이벤트 메타데이터입니다. ${run.trace.omittedPayloadCount}개 본문이 비공개이므로 전체 재생은 아닙니다.`,
          `Public event metadata. ${run.trace.omittedPayloadCount} payload bodies withheld; not a full replay.`,
        )}
      </p>
    </section>
  );
}
