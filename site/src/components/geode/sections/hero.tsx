"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useLocale, t } from "../locale-context";
import { GEODE_SOT } from "@/data/geode/sot";

const videoTabs = [
  { id: "demo", labelKo: "에이전트 및 스캐폴드 시연", labelEn: "Agent & Scaffold demo", src: "https://www.youtube.com/embed/1IftYShGxak", title: "GEODE Agent Demo" },
  { id: "computer-use", labelKo: "Computer-use", labelEn: "Computer-use", src: "https://www.youtube.com/embed/BKg3D6pXwss", title: "GEODE Computer-use Demo" },
  { id: "intro", labelKo: "개발자 소개 / 구조 / 발전사", labelEn: "Introduction / architecture / history", src: "https://www.youtube.com/embed/Qt3jsR5zOcQ", title: "GEODE Introduction" },
];

export function HeroSection() {
  const locale = useLocale();
  const [activeVideo, setActiveVideo] = useState("demo");
  const activeTab = videoTabs.find((tab) => tab.id === activeVideo) ?? videoTabs[0];
  return (
    <section className="relative pt-28 pb-24 px-6">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-baseline justify-between mb-12">
          <span className="font-mono text-[11px] tracking-[0.18em] uppercase text-[var(--ink-3)]">
            GEODE / portfolio
          </span>
          <span className="font-mono text-[11px] text-[var(--ink-3)] border border-[var(--rule)] rounded px-2 py-0.5">
            v{GEODE_SOT.version}
          </span>
        </div>

        <h1 className="font-display tracking-tight text-[var(--ink)] text-[clamp(3rem,8vw,5rem)] leading-[1.02] font-semibold">
          GEODE
        </h1>
        <p className="mt-4 font-display text-[clamp(1.35rem,2.7vw,1.75rem)] text-[var(--ink-1)] leading-snug">
          {t(
            locale,
            "스스로를 고쳐 쓰는 자율 에이전트 하네스.",
            "A self-rewriting agent harness for autonomous execution."
          )}
        </p>

        <div className="mt-10 text-[var(--ink-1)] leading-[1.75] text-[16px]">
          <p>
            {t(
              locale,
              "GEODE는 비-파라메트릭 계열의 자기 진화 에이전트입니다. 모델 가중치는 절대 건드리지 않습니다. 대신 자기 자신을 둘러싼 스캐폴드, 즉 시스템 프롬프트와 도구 정책, 작업 분해와 반성 루프, 스킬 카탈로그를 직접 바꿔 나아집니다.",
              "GEODE is a self-evolving agent on the non-parametric branch. It never updates model weights. Instead it improves by mutating the scaffolding around itself: its system prompt, tool policy, task decomposition, reflection loop, and skill catalog."
            )}
          </p>
          <p className="mt-3 text-[var(--ink-2)]">
            {t(
              locale,
              "변화의 적합도는 능력 벤치마크가 아니라 적대적 안전 감사로 측정합니다. 핵심 안전 차원에는 하한선이 있어, 그 선을 넘어 후퇴하는 변화는 거부합니다.",
              "Its fitness signal is an adversarial safety audit, not a capability benchmark. Critical safety dimensions sit behind a hard floor: a change that regresses them is rejected."
            )}
          </p>
        </div>

        {/* Hero centerpiece: the run command as a prominent copyable panel. */}
        <div className="mt-12 rounded-lg border border-[var(--rule)] bg-[var(--code-bg)] px-6 py-5 font-mono text-[15px] leading-loose text-[var(--code-text)]">
          <div className="text-[var(--ink-3)] text-[11px] tracking-[0.18em] uppercase mb-3">
            {t(locale, "한 줄로 실행", "run it")}
          </div>
          <div>
            <span className="text-[var(--acc-artifact)] font-medium">{"▸"}</span>{" "}
            <span className="text-[var(--ink-3)]">uv run geode</span>{" "}
            <span className="text-[var(--code-string)]">&quot;inspect this repo and summarize release blockers&quot;</span>
          </div>
        </div>

        <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link
            href="/docs"
            className="inline-flex items-center gap-2 px-4 py-2 rounded bg-[var(--acc-artifact)] text-[var(--paper)] font-medium text-[14px] hover:bg-[var(--acc-soft)] transition-colors"
          >
            {t(locale, "문서 읽기", "Read the docs")} {"→"}
          </Link>
          <div className="flex items-center gap-4 text-[13px] font-mono">
            <Link
              href="https://github.com/mangowhoiscloud/geode"
              target="_blank"
              className="text-[var(--ink-2)] hover:text-[var(--acc-artifact)] transition-colors"
            >
              Source
            </Link>
            <Link
              href="https://rooftopsnow.tistory.com/category/Harness"
              target="_blank"
              className="text-[var(--ink-2)] hover:text-[var(--acc-artifact)] transition-colors"
            >
              {t(locale, "개발 블로그", "Dev Blog")}
            </Link>
          </div>
        </div>
      </div>

      {/* See it run: the three demo videos as a clean row under the hero. */}
      <div className="max-w-4xl mx-auto mt-24">
        <div className="flex items-center gap-2 mb-6">
          <span className="h-px w-6 bg-[var(--acc-artifact)]" />
          <span className="text-[12px] tracking-[0.22em] uppercase text-[var(--acc-artifact)] font-medium">
            {t(locale, "실행 화면", "See it run")}
          </span>
        </div>
        <div className="flex gap-2 mb-4 flex-wrap border-b border-[var(--rule)]">
          {videoTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveVideo(tab.id)}
              className="px-4 py-2 text-[12.5px] font-mono transition-colors whitespace-nowrap"
              style={{
                color: activeVideo === tab.id ? "var(--acc-artifact)" : "var(--ink-3)",
                borderBottom: `2px solid ${activeVideo === tab.id ? "var(--acc-artifact)" : "transparent"}`,
                marginBottom: "-1px",
              }}
            >
              {locale === "en" ? tab.labelEn : tab.labelKo}
            </button>
          ))}
        </div>
        {videoTabs.map((tab) => (
          <div key={tab.id} className="max-w-2xl mx-auto" style={{ display: activeVideo === tab.id ? "block" : "none" }}>
            <div className="relative rounded-lg overflow-hidden border border-[var(--rule)]" style={{ paddingBottom: "56.25%" }}>
              <iframe
                className="absolute inset-0 w-full h-full"
                src={tab.src}
                title={tab.title}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          </div>
        ))}
        <p className="max-w-2xl mx-auto mt-3 text-[13px] text-[var(--ink-3)] font-mono">
          {locale === "en" ? activeTab.labelEn : activeTab.labelKo}
        </p>
      </div>

      {/* Mascot. Sits naturally on the warm dark substrate. */}
      <div className="max-w-3xl mx-auto mt-20 flex items-center gap-3 text-[var(--ink-3)]">
        <Image
          src="/geode/images/geode-idle.png"
          alt="Geodi"
          width={40}
          height={40}
        />
        <span className="font-mono text-[11px]">
          {t(locale, "Geodi. GEODE 마스코트", "Geodi. GEODE mascot")}
        </span>
      </div>
    </section>
  );
}
