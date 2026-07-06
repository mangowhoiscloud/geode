# Crucible 핸드오프 — 세션 간 진척·상태 문서

> 갱신: 2026-07-06 02:00 KST. 설계 SOT = `docs/architecture/crucible.md` (원칙·게이트·판정 기록 전부 거기).
> Added alignment (2026-07-06): iteration-cost scaffold, external cases, and the R1/T1 next loop live
> in `crucible.md` §4.0, §4.3, and §5.2.
> 이 문서는 **실행 상태**의 핸드오프: 무엇이 돌고 있고, 어디에 뭐가 있고, 다음이 뭔지.
> 컨텍스트 배경: FuriosaAI 지원 서사와 연동된 작업이나, 공개 저장소이므로 이 문서엔 엔지니어링 내용만.

## 0. Crucible이 무엇인가 (한 문단)

**capability 축 self-evolving 루프.** v1(seedgen+Petri, safety 축)의 후속이 아니라 **형제** —
promotion protocol(champion chain, paired 판정, frozen ruler, "이진 신호는 평균에 안 섞음")은
공유하되 verifier만 교체: Petri 적대 감사 대신 **τ²-bench 결정론 task-success**로 에이전트
하네스/정책을 진화시킨다. 개선 후보를 게이트 사다리 v2(G0 static → G1 trace-replay → G2
micro-sim → G3a targeted → G3b sequential futility → G3c full → G4 held-out → G5 safety →
G6 cost → G7 판정)에 통과시켜 살아남는 승격만 남긴다. 분류: constrained, verifier-guarded
stochastic hill climbing.

## 1. 현재 상태 (2026-07-06 — 실측/판정 일시정지, 코드 반영 완료)

**API 경로 3종이 전부 막혀 새 τ² 실측은 불가. 코드·문서는 정리·반영 완료. 다음은 결정 대기.**

- **clop48 트랙(Claude 구독 opus-4-8): 무효 확정.** 4런 완주했으나 옛 계정(Max 20x)의 7d 창
  소진 후 태스크가 rate-limit 주입으로 오염 → max_steps 지배. **user-sim은 무결**(초기 진단
  오진, 철회). 클린(user_stop) 데이터에 `sequential_gate.py` 적용: **retail CONTINUE(P=0.87,
  flip 3 reg 0), telecom PROMOTE_CAND(P=0.96, flip 4 reg 0)** — 오염 제거하니 S5 유망.
- **API 창 현황**: payg(gpt-5.2)=billing 차단 / Codex 구독=07-07 16:53 리셋 / 옛 Claude 20x=
  07-11 리셋 / **새 계정 Claude Max 5x = 여유(5h 6%·7d 1%)**. 단 5x는 opus 대량엔 빠듯.
- **오늘 코드 반영**: 브랜치 `feature/crucible-tau2-harness` (main 미머지, push 안 함) —
  인프라 버그 5종 수정 2커밋 + Crucible 문서·sequential_gate + handoff + PR-prep hardening.
  See §4.

**S5 판정을 진전시키려면 새 τ² 실측이 필요하나, 지금은 불가.** However, the next loop can
proceed without new live measurements: build a failure manifest from the 41 clean failures, then
screen R1(retail commit-plan guard) and T1(telecom workflow-completion guard) with G1 trace replay
first. See §7.

## 2. 트랙 현황

| 트랙 | 스펙 | 상태 |
|---|---|---|
| **payg (gpt-5.2)** | agent gpt-5.2 high payg + native user_sim gpt-4.1 | M1(S1 프롬프트) **기각 확정**. S5 측정 71건 미완(retail 18·telecom 53) — **OpenAI billing 한도 차단**, 상향 시 ~$65로 완결 가능. 미측정 ID = `tmp/s5_infra_{retail,telecom}.txt` |
| sub55 (gpt-5.5 구독) | 폐기 | Codex 플랜(prolite) 주간 창 소진, 리셋 07-07 16:53 KST. r1/r2 데이터 전량 오염 폐기 |
| clop48 (opus-4-8 구독) | 위 §1 | **무효 확정, 재측정 대상**. 7d usage 소진 후 rate-limit 주입이 max_steps로 오완료돼 판정 금지. clean subset 은 방향 신호만 |

병합 금지: 트랙 간 수치 병합·평균 절대 금지 (스펙 상이). 오염 필터 규칙 = termination_reason
infrastructure_error 제외 ∧ 메시지 error ≥3 제외.

## 3. 판정 기록 (상세는 crucible.md §5)

- **M1 (S1 행동 완결 프롬프트): 기각.** retail 76.3→78.1 (flip 12 vs 회귀 10, p=0.416),
  telecom 87.7→83.3 (p=0.885, 점추정 음). 방향 신호(실패 서브셋 flip 39%)가 전체 paired에서
  재추첨 노이즈로 판명 — 실패분만 재실행하면 회귀가 안 보인다는 설계 경고의 실증.
- **S5 (결정론 종료 가드) payg 트랙: 미완.** 클린 병합 retail +3.1pt(p=0.332)·telecom -3.3pt.
  71건 미측정 상태로 보류. clop48이 cross-family 재판정 중.
- **노이즈 바닥 실측**: pass^1 K=1 태스크당 flip ~20% → 검출 한계 ~8pt. 하네스 개입 효과(~3pt급)는
  K=3 replicate 없이 검출 불가. 사전 등록(K=3, discordant 정확 이항 단측 p<0.05, 승격 상한 2)이
  선택이 아니라 필수임의 데이터 확증.

## 4. 코드 반영 상태 (2026-07-06)

**브랜치 `feature/crucible-tau2-harness` (main 미머지, push 안 함) — 6커밋:**
| 커밋 | 내용 |
|---|---|
| `ee8c5ffde` fix(codex-oauth) | ① `_codex_sdk_workaround.py` install() 무락 레이스 → 동시성 RecursionError (락+클로저 캡처+멱등 마커) |
| `c9b9566e0` fix(anthropic-oauth) | ②③④ 구독 경로 3결함: x-api-key→Bearer(oauth-2025-04-20 베타) / 신원 독립 첫 system 블록(연결형 429) / 토큰 회전 sha256 무효화 |
| `e63f21676` docs(crucible) | crucible.md·crucible-handoff.md·`scripts/eval/sequential_gate.py` |
| `0b6faef08` docs(changelog) | 0.99.276 — Architecture/Added/Fixed/Known Issues |
| `a371a2ad8` docs(crucible) | 세션 간 핸드오프 최신화 — 트랙 차단·결정 대기·업계 지형 반영 |
| latest fix/docs | PR-prep hardening — OAuth identity block을 text-completion/web-search helper 경로까지 적용, `sequential_gate.py` 출력/기본 경로 정리, 테스트 보강 |

- 실험 코드(S5 종료 가드·S1 프롬프트)는 main에 **미반입** — 판정 미완/기각이라 champion chain
  규율상 코어 진입 불가. 브랜치 아카이브로만 보존(§5).
- **미수정 버그(⑥, CHANGELOG Known Issues)**: rate-limit 에러가 대화 메시지로 주입돼
  `infrastructure_error` 격리를 우회 → max_steps 오완료. 어댑터 레벨 격리가 정식 수정(pending).
- Lesson: running external benchmarks at high concurrency is itself a runtime-defect discovery
  mechanism. All six bugs in this cycle surfaced that way.

## 4.5 Industry Landscape Result (2026-07-06 — Cascade Scope Recalibration)

After considering custom cascade/parallel evaluation, the scan showed that existing frameworks
already cover most of that surface:
- **AlphaEvolve/FunSearch**: LLM candidate + automated evaluator + archive/selection loop. The core
  value is evaluator throughput and archive reuse, not the mutator itself.
- **AutoTVM/Ansor/TVM MetaSchedule/Triton**: the canonical semiconductor/compiler answer to
  iteration-cost pressure: put cost models, surrogates, and staged measurement before full hardware
  runs.
- **AlphaChip/ChipNeMo**: automating peripheral loops such as placement, EDA scripts, and bug triage
  has higher ROI than trying to automate the whole core design at once. This aligns directly with
  Furiosa AX-style roles.
- **SWE-bench/SWE-agent/OpenHands/Agentless**: localization, interface design, and cheap patch
  validation often matter more than making the loop more agentic.
- **Hyperband/multi-fidelity BO/sequential testing**: spend small budgets to reject many candidates,
  then add expensive budget only to promising or uncertain candidates. `sequential_gate.py` is a G3b
  component in this lineage.
- **ShinkaEvolve** (Sakana, ICLR 2026): pluggable evaluator + prompt/scaffolding evolution +
  island/archive. It does not have sequential hypothesis testing or paired comparison; noise is
  absorbed by aggregation.
- **FlashEvolve**: non-parametric artifact evolution (system prompt/harness) + async parallel orchestration
  with demonstrated **3.5× throughput** + speculative early rejection.
- **OpenEvolve**: open-source AlphaEvolve-style interface: initial code + evaluator + metrics.
- **AutoPass/KernelAgent**: cheap-to-expensive cascade for verifier-rich domains
  (syntax → schema → runtime).
→ **Conclusion: a custom cascade runner, evaluator port layer, and parallel evaluator would mostly
   reinvent existing work. The unique contribution is statistically disciplined early rejection under
   a noisy verifier, i.e. paired Bayesian futility in `sequential_gate.py`.** The current bottleneck,
   however, is not G3b alone. The missing piece is a **multi-fidelity scaffold** that operates G0-G3a
   automatically. Whether to keep that locally or mount it into a ShinkaEvolve evaluator slot remains
   a §7 decision.

## 5. 워크트리·브랜치 지도

| 워크트리/브랜치 | 역할 |
|---|---|
| `feature/crucible-tau2-harness` (main 워킹트리) | **오늘 반영분** — 인프라 수정 + 문서 + sequential_gate. 리뷰 후 머지 결정 |
| `.claude/worktrees/sev2-m1` / `feature/sev2-m1-action-discipline` | S1 변이(기각) — 아카이브 |
| `.claude/worktrees/sev2-s5` / `feature/sev2-s5-termination-guard` | S5 변이 팔 + 오케스트레이터/판독 스크립트 + 인프라 수정(base와 동일) |
| `.claude/worktrees/sev2-s5-base` / `exp/sub55-base` | baseline 팔 (S5 없음, 인프라 수정만) — 오늘 인프라 커밋의 소스 |

## 6. 파일 지도

- 설계·판정 SOT: `docs/architecture/crucible.md` (§4.2 게이트 v2·§5.1 limiting reagent 결론)
- prompt language rule: design rationale may be Korean, but **system prompt and guard text must be
  recorded as English source text**
  (see `crucible.md` §4.4 R1/T1 scaffold)
- failure manifest generator: `scripts/eval/build_failure_manifest.py` → `tmp/crucible_failure_manifest.json`
  (41 failures + 187 pass controls; no live model calls)
- G1 trace replay: `scripts/eval/trace_replay_gate.py` → `tmp/crucible_g1_trace_replay.json`
  (R1 `PASS_TO_G2_WITH_CONTROLS`, T1 `PASS_TO_G2`; no live model calls)
- tau2 runner guard/snapshot surface: `plugins/benchmark_harness/tau2_geode_agent.py`
  (`--agent-guard {none,r1,t1}`, `--trajectory-snapshot-dir`,
  `<run-id>.trajectory.json`, `<run-id>.snapshot.json`)
- sequential gate: `scripts/eval/sequential_gate.py` (인자 없이 실행 → clop48 clean 재현)
- 실행 스크립트(sev2-s5/tmp/): `run_clop48_overnight.zsh`(창 가드·리프레셔), `analyze_g3_flips.py`
- 재측정 ID: `sev2-s5/tmp/clop48_remeasure_{dom}.txt`(오염 union), `clop48_contaminated_{dom}_{arm}.txt`
- M0 진단 ID: `geode/tmp/tau2_failed_{retail,telecom}.txt`, `s5_infra_{retail,telecom}.txt`
- 공개 ledger: `site/src/data/geode/benchmark-measurements.ts` (리비전 명시·평균 금지 규율)
- OAuth 물질화: `~/.claude/oauth-token.json` (0600, keychain 'Claude Code-credentials'에서 덤프,
  ~1h 만료 — `run_clop48_overnight.zsh::refresh_token()` 스니펫 참조). **버그④ 수정 후엔 어댑터가
  회전 자동 반영하므로, 프로덕션 경로는 재덤프 불필요; 스크립트는 창 헤더 조회용으로만 유지**
- 포트폴리오(비공개): `~/Downloads/GEODE-포트폴리오/Crucible-덱-설계.md`,
  resume `furiosa/.../interview-prep.md` 자산 8

## 7. 다음 액션 큐 (결정 대기 포함)

**Decisions Needed (User):**
- D1. **Resolved for the current loop: PAYG-free / subscription-only.** Hold the PAYG `gpt-5.2`
  confirmation lane. Use `gpt-5.5` Codex/ChatGPT subscription as a new product-route baseline and run
  base-vs-candidate paired checks only within that same model/user route. Local routing, OpenAI Codex
  docs, and live probe on 2026-07-06 agree: this account rejects subscription `gpt-5.2` with 400 and
  accepts subscription `gpt-5.5`. Do not average subscription results with PAYG `gpt-5.2`.
- D2. **`sequential_gate` placement**: keep it locally (lightweight) vs mount it in a ShinkaEvolve
  evaluator slot (avoid reinvention; get island/archive/parallel orchestration; accept dependency).
  See §4.5.

**Execution Queue:**
1. **Done**: build a failure manifest from the 41 clean failures plus matched pass controls
   (`cluster`, `expected_write`, `actual_write`, `intervention_turn`, `candidate_guard`,
   `false_positive_risk`). Command: `uv run python scripts/eval/build_failure_manifest.py`.
   Output: `tmp/crucible_failure_manifest.json` with 41 failures and 187 controls.
2. **Done**: run deterministic G1 trace replay. Command:
   `uv run python scripts/eval/trace_replay_gate.py`. Result: R1 `PASS_TO_G2_WITH_CONTROLS`
   (24/27 supported, 4/87 controls blocked: task IDs 2, 46, 64, 73), T1 `PASS_TO_G2`
   (14/14 supported, 0/100 controls blocked).
3. Design R1/T1 separately. R1 = retail commit-plan guard for order/item/address/payment
   verification. T1 = telecom workflow-completion guard for issue-specific terminal verifiers.
   Do not bundle them into one mutation. Write the actual system-prompt/guard text in English.
4. **Blocked before live G2**: route readiness failed on the first T1 baseline micro-sim attempt
   (`crucible-tau2-g2-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n2k1-20260706-a`).
   The run was interrupted after repeated Codex subscription `empty output_text` completions; tau2
   checkpointed 0 simulations, so it is infra evidence only, not performance evidence. The tau2
   GEODE runner now hard-fails an empty visible turn with no projected tau2 tool call by default.
   A second 1-task readiness probe
   (`crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-xhigh-openai-sub-gpt55-high-n1k1-20260706-a`)
   showed the empty output can occur inside internal reflection/recovery calls and still finish as
   `max_steps`; that run is also contamination evidence only. The runner now sets
   `GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT=1` by default so codex-oauth raises on any empty subscription
   response, sets `GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR=1` so AgenticLoop propagates adapter
   failures instead of retrying, disables AgenticLoop cognitive reflection by default, preserves and
   replays prior Codex `response.output` items per official Responses API state-management guidance,
   sanitizes replayed output items for the Codex subscription input validator (`status` and top-level
   `None` fields), allows function-call-only turns with empty visible text, and scans for new
   `~/.geode/diagnostics/codex-oauth-empty-text/*.json` dumps after snapshotting. It also exposes
   `--max-retries` and defaults it to 0 so tau2 does not retry infrastructure failures.
   `--allow-empty-geode-turn`, `--enable-cognitive-reflection`, and
   `--disable-codex-output-replay` are debug-only.
   Latest readiness run
   `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-output-replay-e`
   evaluated 1 simulation without infra contamination and wrote a trajectory snapshot, but ended
   `max_steps` / reward 0.0 after reaching the SIM-reseat/mobile-data step. **Route is now usable
   for tiny subscription-only probes; quality/termination is still poor.**
5. Cheap termination-focused telecom loop ran:
   - T1 terminal-verifier prompt:
     `crucible-tau2-cheaploop-telecom-candidate-t1-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
     -> evaluated, `max_steps`, reward 0.0, 24 messages; premature `can_send_mms`, no bundled
     user actions.
   - T2 agent step-economy prompt:
     `crucible-tau2-cheaploop-telecom-candidate-t2-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-b`
     -> infra error after long history; invalid as performance evidence.
   - T3 agent + user step-economy prompts:
     `crucible-tau2-cheaploop-telecom-candidate-t3-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-c`
     -> evaluated, `max_steps`, reward 0.0, 36 messages; user tool bundling appeared but opened
     extra troubleshooting branches.
   **Verdict: prompt-only telecom guards are insufficient. Do not run scored G2 yet.**
6. Deterministic telecom G2 surrogate is now implemented:
   `scripts/eval/telecom_workflow_gate.py`. It consumes tau2 `results.json`, writes
   `tmp/crucible_telecom_workflow_gate.json`, and rejects trajectories that violate blocker order,
   exceed message/tool budgets, miss `can_send_mms == true`, or contain infrastructure failures.
   Applied to the current four trajectories: baseline-e = `REJECT_SURROGATE`, T1-a =
   `REJECT_SURROGATE`, T2-b = `INVALID_INFRA`, T3-c = `REJECT_SURROGATE`. Next candidate must pass
   this zero-live gate before paired G2.
7. Telecom Action Planner scaffold is now implemented:
   `scripts/eval/telecom_action_planner.py`. It emits a bounded MMS blocker bundle
   (`toggle_airplane_mode`, `reseat_sim_card`, `toggle_data`, `set_network_mode_preference`,
   `reset_apn_settings`, `reboot_device`, `check_apn_settings`) and delays `can_send_mms` until
   blockers are known clear. Demo output lives at `tmp/crucible_telecom_action_plan.json`; synthetic
   trajectory `tmp/crucible_telecom_action_plan.synthetic_results.json` passes
   `telecom_workflow_gate.py` as `PASS_SURROGATE` (messages=14, calls=8). This is zero-live coherence
   only.
8. Telecom planner live wiring has a first negative result:
   `--agent-planner telecom-mms-v1` is wired into the tau2 runner, and the runner now exposes
   benchmark-only cost controls `--agent-max-rounds`, `--user-max-rounds`, and
   `--disable-tool-search-defer`. The capped/no-defer probe
   `crucible-tau2-cheaploop-telecom-candidate-planner-capped-nodefer-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   evaluated without infra contamination but ended `max_steps`, reward 0.0, 15 messages, and
   **0 projected tau2 tool calls**. Surrogate verdict: `REJECT_SURROGATE` (`max_steps`, missing
   terminal `can_send_mms == true`). Lesson: raw short-turn pressure can suppress environment
   action. The **action-before-talk** precondition is now implemented in
   `telecom_workflow_gate.py`: after identity is available, a cheaploop trajectory must project at
   least one backend/environment tool action before manual phone checklist loops. Replaying the
   capped/no-defer run now rejects with `missing_action_before_manual_checklist`.
9. Main-loop alignment is now implemented: `core.agent.verify` has an opt-in
   `GEODE_VERIFY_ACTION_BEFORE_TALK=1` rule that emits retryable
   `manual_checklist_without_action` failures when the loop talks through phone/network checklists
   without tool action. `tau2_geode_agent.py` enables this by default and records
   `action_before_talk_verify` in trajectory snapshots. The deterministic
   `telecom_action_planner.py` is only a scaffold/fixture generator; do not grow it into a separate
   behavior path unless GEODE's main loop cannot express the policy.
10. Two live main-loop-alignment probes ran on the same MMS easy task:
   - baseline + main-loop action-before-talk verifier:
     `crucible-tau2-readiness-telecom-baseline-none-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-mainverify-a`
     → route ready, no infra contamination, 7 tool calls, snapshot written, but
     `REJECT_SURROGATE` (`premature_can_send_mms`, `max_steps`, missing terminal success).
   - T1 guard + main-loop action-before-talk verifier:
     `crucible-tau2-cheaploop-telecom-candidate-t1-mainverify-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
     → same `REJECT_SURROGATE` and same call order as baseline: account reads →
     premature `can_send_mms` → `check_network_status` → `toggle_airplane_mode`.
   **Conclusion: action projection is fixed enough for readiness, but T1 prompt guard does not fix
   workflow ordering. Do not run scored G2.**
11. Next valid candidate: a telecom workflow-order surface, not another plain prompt guard. For MMS,
   treat `can_send_mms` as a terminal verifier: it must be delayed until network status, airplane
   mode, SIM, mobile data/network mode, and APN/MMSC blockers are cleared or explicitly ruled out.
   Scaffold now exists:
   - `plugins/benchmark_harness/tau2_workflow_order.py::TelecomMmsWorkflowOrder` tracks blocker
     state from tau2 tool outputs and renders `<crucible_workflow_order>` dynamic context.
   - `tau2_geode_agent.py --agent-workflow-order telecom-mms-v1` enables it for the agent turn.
   - Snapshot metadata records `agent_workflow_order`; assistant raw metadata records
     `geode_workflow_order` and `geode_premature_terminal_tools`.
   Next tiny live command should use `--agent-workflow-order telecom-mms-v1` and remain
   reject-only until `telecom_workflow_gate.py` returns `PASS_SURROGATE`.
   Live result now exists:
   `crucible-tau2-cheaploop-telecom-candidate-workfloworder-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   → `REJECT_SURROGATE`, but `premature_can_send_mms` is gone. Calls became account reads →
   `check_network_status` → `toggle_airplane_mode` → `check_network_status` → `reseat_sim_card`.
   Remaining blockers: `max_steps`, missing terminal success. **Next scaffold should preserve this
   ordering and add step-economy pressure/bundled safe phone actions.**
   Subscription exhaustion check: current OpenAI subscription route has no reliable local remaining
   usage meter. For these runs, do not infer exhaustion without evidence, and do not infer guaranteed
   remaining quota merely because the route produced text. The evidence channels are:
   new `codex-oauth-empty-text/*.json` diagnostics, adapter exception propagation,
   `infrastructure_error`, or rate-limit/quota text inside the tau2 transcript. The 2026-07-06 cheap
   probes had none of those; latest empty-output dump was 07:54:57 KST, and transcript hits for
   `billing`/`usage`/`429` were policy/timestamp false positives. Treat failures as behavioral
   `max_steps` unless a new hard evidence channel appears.
   Step-economy scaffold now exists: use
   `--agent-workflow-order telecom-mms-step-economy-v1` for the next cheap probe. It preserves the
   terminal-verifier ordering but asks the user simulator to bundle safe prerequisite phone actions
   after one diagnostic result exposes multiple blockers. Still reject-only; no scored G2 until
   `telecom_workflow_gate.py` returns `PASS_SURROGATE`.
   Live result now exists:
   `crucible-tau2-cheaploop-telecom-candidate-stepeconomy-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   → `REJECT_SURROGATE`, no exhaustion evidence, slight economy gain only (24→23 messages, 7→6
   calls). User simulator still replied "one step at a time" and split actions. Next diagnostic is
   user-side coupling with `--user-prompt-append-file scripts/eval/telecom_user_step_economy_guard.md`
   to isolate whether `max_steps` is agent policy or simulated-user friction. This is measurement
   diagnosis, not promotion evidence.
   User-side coupling diagnostic now exists:
   `crucible-tau2-cheaploop-telecom-diagnostic-stepeconomy-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   → `REJECT_SURROGATE`, no exhaustion evidence, but free-form user bundling overcorrected to 36
   messages / 21 calls, premature `can_send_mms`, and message/tool budget failures. Next valid
   candidate is bounded, not freer: use
   `--agent-workflow-order telecom-mms-bounded-bundle-v1` with no user-side guard. It should request
   at most one explicit prerequisite bundle, exclude `can_send_mms` from that bundle, then spend a
   separate terminal verifier only after tracked blockers are clear.
   Bounded-bundle live result now exists:
   `crucible-tau2-cheaploop-telecom-candidate-boundedbundle-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   → `REJECT_SURROGATE`, no usage-exhaustion evidence, 24 messages / 7 calls,
   `multi_tool_user_turns=2`, no premature terminal verifier. It still hit `max_steps`; the simulated
   user refused the initial bundle and the run ended with `non_2g_network=false`, `apn_valid=false`,
   and no terminal `can_send_mms`. Gate output:
   `tmp/crucible_telecom_workflow_gate_boundedbundle_a.json`.
   Next diagnostic, if needed, is bounded user-side coupling:
   `--user-prompt-append-file scripts/eval/telecom_user_bounded_bundle_guard.md`. This changes the
   evaluator route, so it is measurement diagnosis only, not promotion evidence. Scored G2 remains
   blocked until an agent-route-only candidate passes `telecom_workflow_gate.py`.
   Bounded user-side diagnostic now exists:
   `crucible-tau2-cheaploop-telecom-diagnostic-boundedbundle-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   → `REJECT_SURROGATE`, no usage-exhaustion evidence, 32 messages / 15 calls. It reached terminal
   `can_send_mms`, but MMS was still false after basic blockers cleared. Task/source inspection showed
   the hidden blocker is roaming: `user_abroad_roaming_disabled_off` requires both account-side
   `enable_roaming` and phone-side roaming on.
   Agent-only roaming recovery now exists:
   `--agent-workflow-order telecom-mms-roaming-recovery-v1`, live run
   `crucible-tau2-cheaploop-telecom-candidate-roamingrecovery-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   → `REJECT_SURROGATE`, no usage-exhaustion evidence, 24 messages / 7 calls. It did **not** reach
   roaming recovery; native user-sim again rejected the initial bundle and the run stopped at
   `toggle_data`. Current blocker: native tau2 user-sim step friction, not the roaming recovery rule.
   Next choice: design a smaller native-user phase protocol, or keep bounded-bundle user route as
   diagnostic-only and do not claim promotion.
   Smaller phase protocol now exists:
   `--agent-workflow-order telecom-mms-phased-recovery-v1`, live run
   `crucible-tau2-cheaploop-telecom-candidate-phasedrecovery-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   → `REJECT_SURROGATE`, no usage-exhaustion evidence, 21 messages / 4 calls. It reduced spend but
   still followed one-action-at-a-time and stopped at pending `toggle_data`.
   Roaming-recovery + bounded user diagnostic now exists:
   `crucible-tau2-cheaploop-telecom-diagnostic-roamingrecovery-userguard-openai-sub-gpt55-high-openai-sub-gpt55-high-n1k1-20260706-a`
   → `REJECT_SURROGATE`, no usage-exhaustion evidence, 31 messages / 15 calls. It reached
   `can_send_mms=false`, inspected line details/data usage, saw active line `roaming_enabled=false`,
   but still branched to Wi-Fi calling instead of `enable_roaming` + phone-side roaming. Next useful
   change is a hard ordering gate: after `mms_failed_after_prereqs=true` and active-line
   `roaming_enabled=false`, block Wi-Fi/app-permission/escalation branches until roaming is repaired
   or explicitly ruled out. Do not spend more live probes before that gate exists.
12. After a workflow-order candidate passes the tiny live surrogate: run T1/T3 replacement
   G2 micro-sim first; then R1
   G2 micro-sim with control task IDs 2, 46, 64, 73 included as canaries before any targeted mini run.
   Run IDs must follow:
   `crucible-tau2-g2-<domain>-<baseline|candidate>-<none|r1|t1>-<agent_route>-<user_route>-n<N>k<K>-<yyyymmdd>-<seq>`.
   The runner snapshots raw trajectories to
   `artifacts/eval/runs/crucible/trajectory-snapshots/<run-id>.trajectory.json` and metadata to
   `<run-id>.snapshot.json` when `--save-to <run-id>` is set.
13. After G2/G3a subscription-only paired runs, use `sequential_gate.py` for futility/promote-candidate
   verdicts and update `crucible.md` §5. Keep PAYG `gpt-5.2` claims out of this loop.
14. If S5/R1/T1 promotes, do M2 core migration: `core/agent/verify.py` rule-based checks + policy SoT
   thresholds, adapter guard removal, and `system_prompt_override` → wrapper-section composition.
   The current override bypasses the v1 mutation surface (`WRAPPER_PROMPT_SECTIONS`), so the benchmark
   cannot measure core mutations cleanly.
15. Fix bug ⑥, rate-limit conversation injection isolation, then bring it into main.
16. `feature/crucible-tau2-harness` 리뷰 → main 머지/push (사용자 승인 시).
17. airline 50건 trend + comparator run(tau2 내장 `llm_agent`, "GEODE vs 바닐라") — subscription
   route로 별도 product-route comparison 가능할 때만.
18. 수치 확정 후: ledger 행 + Crucible 덱 빌드(KO/EN) + 이력서 GEODE Self-improving 불릿 교체.

## 8. 함정 목록 (재발 방지)

- tau2 `--task-ids`는 `--num-tasks`(기본 1!)로 뒤에서 슬라이스 — 항상 ID 수와 같게 명시.
- 실패 서브셋만 재실행한 flip rate는 방향 신호일 뿐(회귀 안 보임) — 전체 paired 전 공개 금지.
- quota 사망 중 완료된 run을 무필터로 읽으면 변이 효과로 오독(§2 오염 필터 필수).
- 세션 소유 백그라운드는 세션 종료와 함께 죽음 — 장기 런은 nohup+disown.
- native tau2 user_simulator는 GEODE 어댑터 우회(litellm→payg 직행) — 구독 트랙은 geode_user 라우트.
- Codex/Claude 구독 창은 조회 표면 없음(Claude는 응답 헤더로 가능) — 런 전 창 가드 필수.
