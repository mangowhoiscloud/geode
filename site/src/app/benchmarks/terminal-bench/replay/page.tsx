import type { Metadata } from "next";
import Image from "next/image";
import { ReplayPlayer } from "./replay-player";
import styles from "./replay.module.css";

export const metadata: Metadata = {
  title: "Terminal-Bench 2.1 Replay | GEODE × Codex",
  description: "445 paired trials in Harbor. Verified, metadata-only ATIF replay; not raw PTY footage or an official leaderboard score.",
  alternates: { canonical: "https://mangowhoiscloud.github.io/geode/benchmarks/terminal-bench/replay/" },
};

export default function ReplayPage() {
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <a href="/geode/docs/benchmarks/terminal-bench/">Terminal-Bench docs</a>
          <h1>Terminal-Bench 2.1</h1>
          <p>GEODE × Codex. Execution replay.</p>
        </div>
        <Image src="/geode/benchmarks/terminal-bench/harbor-wordmark.png" alt="Harbor" width={164} height={52} priority />
      </header>
      <ReplayPlayer />
      <noscript>JavaScript is required for playback. The linked documentation contains the evidence coverage and limitations.</noscript>
    </main>
  );
}
