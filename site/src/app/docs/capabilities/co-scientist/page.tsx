import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Co-Scientist Loop — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/co-scientist"
      title="Co-Scientist Loop"
      titleKo="Co-Scientist 루프"
      summary="The seed-generation pipeline's actual co-scientist loop: a multi-phase candidate generator scored by an Elo tournament and improved by an evolver across N iterations. Implemented in plugins/seed_generation/orchestrator.py."
      summaryKo="seed-generation 파이프라인의 실제 co-scientist 루프. 다단계 후보 생성 → Elo 토너먼트 평가 → evolver 개선을 N 회 반복합니다. plugins/seed_generation/orchestrator.py 구현."
    >
      <Bi
        ko={
          <>
            <h2>무엇을 하는 루프인가</h2>
            <p>
              Google AI Co-Scientist 의 generate → review → rank → evolve 멀티
              에이전트 흐름을 GEODE 의 Petri seed 생성에 이식한 루프입니다. 한
              target_dim (예: redundant_tool_invocation) 에 대해 후보 seed 들을
              생성하고, 3-voter Elo 토너먼트로 순위를 매기고, 상위 survivor 를
              evolver 가 변이시켜 다음 세대로 넘깁니다. <code>plugins/seed_generation/orchestrator.py</code>
              의 <code>Pipeline.arun</code> 이 phase 순서대로 sub-agent 를 fan-out 합니다.
            </p>

            <h2>Phase 순서 (iteration 0, 초안 생성)</h2>
            <pre>{`supervisor          전략 합성 → state.supervisor_guidance + phase_guidance.*
literature_review   외부 논문 분석 (max_papers > 0 일 때만)
generator           후보 seed 생성 (debate_transcripts 다중 턴)
proximity           유사도 클러스터링 → similarity_clusters
critic              후보별 reflection (target_dim 기준)
pilot               후보 pilot 채점 → pilot_scores[cid][dim]
ranker              3-voter Elo 토너먼트 → elo_ratings + survivors
evolver             survivor 변이 → evolved_candidates
meta_reviewer       coverage / gap 분석 → next_gen_priors`}</pre>

            <h2>Iteration 1..N (반복 사이클)</h2>
            <p>
              <code>max_iterations &ge; 1</code> 이면 meta_reviewer 이후
              evolved_candidates 를 candidates 로 승격하고 아래 5 phase 만 다시
              돕니다. supervisor / literature / generator / proximity 는 재실행하지
              않습니다 (새 초안이 아니라 진화된 후보를 다듬는 단계이므로).
            </p>
            <pre>{`critic → pilot → ranker → evolver → meta_reviewer   (× N)`}</pre>

            <h2>Elo 토너먼트 (ranker)</h2>
            <p>
              각 후보는 1000 에서 시작합니다. 매치마다 3-voter 패널이 투표하고,
              과반(&ge;2/3)이면 A 또는 B 가 승자, 그 외에는 tie(0.5/0.5)로
              처리되어 양쪽 rating 이 갱신됩니다. 유효 표가 2 미만이면
              quorum_lost 로 매치를 건너뛰고 rating 은 불변입니다. Elo 는{" "}
              <code>R += K &middot; (S - E)</code> (K=32, E 는 로지스틱 기대값)로
              갱신됩니다. 최종 rating 상위 5 가 survivor 입니다. 자세한 식은{" "}
              <code>plugins/seed_generation/tournament.py</code> + 토너먼트 페이지의
              "how Elo is computed" 참고.
            </p>

            <p className="text-white/40 text-sm"><em>참조</em>: <code>plugins/seed_generation/orchestrator.py</code> (<code>_PHASE_ORDER</code> / <code>_ITERATION_PHASE_ORDER</code>), <code>plugins/seed_generation/agents/ranker.py</code>, <code>plugins/seed_generation/tournament.py</code>. 개발 워크플로우(worktree → PR → merge)를 다루던 이전 cycle-skill 문서와는 별개입니다.</p>
          </>
        }
        en={
          <>
            <h2>What the loop does</h2>
            <p>
              A port of Google AI Co-Scientist's generate, review, rank, evolve
              multi-agent flow onto GEODE's Petri seed generation. For one
              target_dim (e.g. redundant_tool_invocation) it drafts candidate
              seeds, ranks them with a 3-voter Elo tournament, and mutates the
              top survivors into the next generation. <code>Pipeline.arun</code>{" "}
              in <code>plugins/seed_generation/orchestrator.py</code> fans out a
              sub-agent per phase in order.
            </p>

            <h2>Phase order (iteration 0, initial draft)</h2>
            <pre>{`supervisor          strategy synthesis -> state.supervisor_guidance + phase_guidance.*
literature_review   external paper analysis (only when max_papers > 0)
generator           draft candidate seeds (multi-turn debate_transcripts)
proximity           similarity clustering -> similarity_clusters
critic              per-candidate reflection (against target_dim)
pilot               pilot scores -> pilot_scores[cid][dim]
ranker              3-voter Elo tournament -> elo_ratings + survivors
evolver             mutate survivors -> evolved_candidates
meta_reviewer       coverage / gap analysis -> next_gen_priors`}</pre>

            <h2>Iterations 1..N (the repeat cycle)</h2>
            <p>
              With <code>max_iterations &ge; 1</code>, after meta_reviewer the
              evolved_candidates are promoted into candidates and only the five
              phases below re-run. Supervisor, literature, generator and
              proximity do not re-run: each cycle refines evolved candidates
              rather than drafting a fresh batch.
            </p>
            <pre>{`critic -> pilot -> ranker -> evolver -> meta_reviewer   (x N)`}</pre>

            <h2>The Elo tournament (ranker)</h2>
            <p>
              Every candidate starts at 1000. Each match's 3-voter panel votes:
              a strict majority (&ge;2 of 3) makes A or B the winner, anything
              else is a tie scored 0.5/0.5 and both ratings still update. Fewer
              than 2 valid votes is a quorum_lost, where the match is skipped
              with no rating change. Elo updates by{" "}
              <code>R += K &middot; (S - E)</code> (K=32, E the logistic
              expected score). The top 5 final ratings are the survivors. The
              full formula is in <code>plugins/seed_generation/tournament.py</code>{" "}
              and the tournament page's "how Elo is computed" block.
            </p>

            <p className="text-white/40 text-sm"><em>References</em>: <code>plugins/seed_generation/orchestrator.py</code> (<code>_PHASE_ORDER</code> / <code>_ITERATION_PHASE_ORDER</code>), <code>plugins/seed_generation/agents/ranker.py</code>, <code>plugins/seed_generation/tournament.py</code>. This is separate from the development-workflow cycle skill (worktree → PR → merge) the previous page described.</p>
          </>
        }
      />
    </DocsShell>
  );
}
