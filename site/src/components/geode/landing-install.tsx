"use client";

import * as Tabs from "@radix-ui/react-tabs";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { t, useLocale } from "@/components/geode/locale-context";

const installChannels = [
  {
    id: "uv-tool",
    labelKo: "uv tool",
    labelEn: "uv tool",
    noteKo: "권장 설치 방법입니다. 최신 안정 버전을 격리된 도구 환경에 설치합니다.",
    noteEn: "Recommended. Install the latest stable release in an isolated tool environment.",
    copy: "uv tool install geode-agent",
  },
  {
    id: "uvx",
    labelKo: "uvx",
    labelEn: "uvx",
    noteKo: "전역 명령을 설치하지 않고 GEODE를 실행합니다.",
    noteEn: "Run GEODE without installing a global command.",
    copy: "uvx --from geode-agent geode",
  },
  {
    id: "source",
    labelKo: "소스",
    labelEn: "Source",
    noteKo: "개발·기여용 소스를 내려받습니다. uv가 프로젝트 환경을 준비하고 실행합니다.",
    noteEn: "Clone the source for development. uv prepares the project environment and runs GEODE.",
    copy: "git clone https://github.com/mangowhoiscloud/geode.git && cd geode && uv run geode",
  },
] as const;

export function InstallCommands() {
  const locale = useLocale();
  const [activeChannel, setActiveChannel] = useState("uv-tool");
  const [copyStatus, setCopyStatus] = useState<"idle" | "copying" | "copied" | "error">("idle");
  const copyRequest = useRef(0);
  const channel = installChannels.find((item) => item.id === activeChannel) ?? installChannels[0];

  useEffect(() => {
    return () => { copyRequest.current += 1; };
  }, []);

  async function copyCommand() {
    const request = ++copyRequest.current;
    setCopyStatus("copying");
    try {
      await navigator.clipboard.writeText(channel.copy);
      if (request === copyRequest.current) setCopyStatus("copied");
    } catch {
      if (request === copyRequest.current) setCopyStatus("error");
    }
  }

  return (
    <Tabs.Root
      value={activeChannel}
      onValueChange={(value) => {
        copyRequest.current += 1;
        setActiveChannel(value);
        setCopyStatus("idle");
      }}
      className="min-w-0"
    >
      <Tabs.List
        aria-label={t(locale, "설치 방법", "Installation method")}
        className="flex flex-wrap gap-2 border-b border-[var(--rule)] pb-3"
      >
        {installChannels.map((item) => (
          <Tabs.Trigger
            key={item.id}
            value={item.id}
            className="min-h-11 min-w-11 touch-manipulation rounded-md px-4 py-2 font-mono text-sm text-[var(--ink-2)] transition-colors hover:bg-[var(--paper-2)] hover:text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--acc-artifact)] data-[state=active]:bg-[var(--paper-2)] data-[state=active]:text-[var(--acc-artifact)] motion-reduce:transition-none"
          >
            {t(locale, item.labelKo, item.labelEn)}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      {installChannels.map((item) => (
        <Tabs.Content
          key={item.id}
          value={item.id}
          className="min-w-0 pt-5 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--acc-artifact)]"
        >
          <p className="text-base leading-relaxed text-[var(--ink-2)]">
            {t(locale, item.noteKo, item.noteEn)}
          </p>
          <pre
            tabIndex={0}
            aria-label={t(locale, "설치 명령", "Install command")}
            className="mt-4 max-w-full overflow-x-auto rounded-md border border-[var(--rule)] bg-[var(--code-bg)] p-5 font-mono text-sm leading-relaxed text-[var(--code-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--acc-artifact)]"
          >
            <code translate="no" className="select-all">{item.copy}</code>
          </pre>
        </Tabs.Content>
      ))}
      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
        <button
          type="button"
          onClick={copyCommand}
          disabled={copyStatus === "copying"}
          className="min-h-11 min-w-11 shrink-0 touch-manipulation rounded-md border border-[var(--acc-line)] px-4 py-2 text-sm font-medium text-[var(--acc-line)] transition-colors hover:bg-[var(--acc-line)] hover:text-[var(--paper)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--acc-line)] disabled:cursor-wait motion-reduce:transition-none"
        >
          {copyStatus === "copying"
            ? t(locale, "복사 중…", "Copying…")
            : t(locale, "명령 복사", "Copy command")}
        </button>
        <p role="status" aria-live="polite" aria-atomic="true" className="min-h-6 text-sm text-[var(--ink-2)]">
          {copyStatus === "copied"
            ? t(locale, "명령을 복사했습니다.", "Command copied.")
            : copyStatus === "error"
              ? t(locale, "복사하지 못했습니다. 위 명령을 선택해 직접 복사하세요.", "Copy failed. Select the command above and copy it manually.")
              : ""}
        </p>
      </div>
      <p className="mt-6 text-sm leading-relaxed text-[var(--ink-2)]">
        {channel.id === "uv-tool" ? (
          <>
            {t(locale, "설치 후 ", "After installation, run ")}
            <code translate="no" className="font-mono text-[var(--ink)]">geode</code>
            {t(locale, "를 실행합니다. ", ". ")}
          </>
        ) : (
          <>{t(locale, "이 명령은 GEODE 세션을 시작합니다. ", "This command starts a GEODE session. ")}</>
        )}
        {t(locale, "세션에서 ", "Inside the session, use ")}
        <code translate="no" className="font-mono text-[var(--ink)]">/login</code>
        {t(locale, "으로 자격 증명을 확인합니다. ", " to review credentials. ")}
        <Link
          href={locale === "ko" ? "/docs/run/pick-path?lang=ko" : "/docs/run/pick-path?lang=en"}
          className="inline-flex min-h-11 items-center text-[var(--acc-aqua)] underline underline-offset-4 hover:text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--acc-aqua)]"
        >
          {t(locale, "인증 방법 선택", "Choose an authentication path")}
        </Link>
      </p>
    </Tabs.Root>
  );
}
