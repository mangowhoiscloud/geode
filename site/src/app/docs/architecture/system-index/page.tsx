import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "System index — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="architecture/system-index"
      title="System index"
      titleKo="시스템 색인"
      summary="The flat catalog: every first-class subsystem with its root path and key entry modules, grouped by the five layers."
      summaryKo="평면 카탈로그입니다. 모든 1급 서브시스템의 루트 경로와 핵심 진입 모듈을 5계층으로 묶어 나열합니다."
    >
      <Bi
        ko={
          <>
            <p>
              이 페이지는 순수한 경로 색인입니다. 경로가 어떻게 이어지는지는{" "}
              <a href="/geode/docs/develop/architecture">아키텍처 심화</a>가,
              계층이 왜 이렇게 나뉘는지는{" "}
              <a href="/geode/docs/explanation/4-layer">왜 5계층인가</a>가
              다룹니다.
            </p>

            <h2>최상위 진입 모듈</h2>
            <table>
              <thead><tr><th>모듈</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><code>core/runtime.py</code></td><td><code>GeodeRuntime</code> 부트스트랩</td></tr>
                <tr><td><code>core/paths.py</code></td><td>모든 디렉터리 경로의 단일 해석 지점</td></tr>
                <tr><td><code>core/mcp_server.py</code></td><td><code>geode-mcp</code> 진입점 (stdio MCP 서버)</td></tr>
                <tr><td><code>core/async_runtime.py</code></td><td>async 이벤트 루프 헬퍼</td></tr>
              </tbody>
            </table>

            <h2>Self-Improving</h2>
            <table>
              <thead><tr><th>서브시스템</th><th>루트</th><th>핵심 모듈</th></tr></thead>
              <tbody>
                <tr><td>루프 드라이버</td><td><code>core/self_improving/</code></td><td><code>train.py</code>, <code>campaign.py</code>, <code>prepare.py</code>, <code>program.md</code>, <code>watch_campaign.py</code></td></tr>
                <tr><td>측정 장비</td><td><code>core/self_improving/</code></td><td><code>measure.py</code>, <code>fitness.py</code>, <code>gate.py</code>, <code>ledger.py</code></td></tr>
                <tr><td>변이 런타임</td><td><code>core/self_improving/loop/</code></td><td><code>mutate/runner.py</code>, <code>mutate/policies.py</code>, <code>observe/baseline_epoch.py</code>, <code>inject/in_context_wiring.py</code>, <code>auto_trigger.py</code></td></tr>
              </tbody>
            </table>

            <h2>Agent</h2>
            <table>
              <thead><tr><th>서브시스템</th><th>루트</th><th>핵심 모듈</th></tr></thead>
              <tbody>
                <tr><td>agentic 루프</td><td><code>core/agent/loop/</code></td><td><code>agent_loop.py</code> (AgenticLoop), <code>models.py</code>, <code>_context.py</code></td></tr>
                <tr><td>서브에이전트</td><td><code>core/agent/</code></td><td><code>sub_agent.py</code>, <code>worker.py</code>, <code>task_isolation.py</code></td></tr>
                <tr><td>시스템 프롬프트</td><td><code>core/agent/</code></td><td><code>system_prompt.py</code>, <code>system_injection.py</code></td></tr>
                <tr><td>가드</td><td><code>core/agent/</code></td><td><code>safety.py</code>, <code>budget.py</code>, <code>approval.py</code>, <code>context_manager.py</code></td></tr>
              </tbody>
            </table>

            <h2>Harness</h2>
            <table>
              <thead><tr><th>서브시스템</th><th>루트</th><th>핵심 모듈</th></tr></thead>
              <tbody>
                <tr><td>thin CLI</td><td><code>core/cli/</code></td><td><code>__init__.py</code> (Typer app), <code>commands/</code>, <code>routing.py</code>, <code>dispatcher.py</code>, <code>ipc_client.py</code>, <code>onboarding.py</code></td></tr>
                <tr><td>serve 데몬</td><td><code>core/server/</code></td><td><code>ipc_server/poller.py</code> (CLIPoller), <code>supervised/</code> (slack/discord/telegram 폴러, webhook, services)</td></tr>
                <tr><td>게이트웨이</td><td><code>core/messaging/</code></td><td><code>binding.py</code> (ChannelManager), <code>models.py</code>, <code>slack_formatter.py</code></td></tr>
                <tr><td>훅</td><td><code>core/hooks/</code></td><td><code>system.py</code> (HookSystem + HookEvent), <code>dispatch.py</code>, <code>discovery.py</code></td></tr>
                <tr><td>오케스트레이션</td><td><code>core/orchestration/</code></td><td><code>lane_queue.py</code>, <code>task_system.py</code>, <code>compaction.py</code>, <code>tool_offload.py</code>, <code>isolated_execution.py</code></td></tr>
                <tr><td>스케줄러</td><td><code>core/scheduler/</code></td><td><code>service.py</code>, <code>triggers.py</code>, <code>nl_scheduler.py</code>, <code>jitter.py</code></td></tr>
                <tr><td>배선</td><td><code>core/wiring/</code></td><td><code>bootstrap.py</code>, <code>container.py</code>, <code>scheduling.py</code>, <code>startup.py</code></td></tr>
                <tr><td>터미널 UI</td><td><code>core/ui/</code></td><td><code>event_renderer.py</code>, <code>latex.py</code>, <code>console.py</code></td></tr>
              </tbody>
            </table>

            <h2>Runtime</h2>
            <table>
              <thead><tr><th>서브시스템</th><th>루트</th><th>핵심 모듈</th></tr></thead>
              <tbody>
                <tr><td>도구</td><td><code>core/tools/</code></td><td><code>registry.py</code>, <code>definitions.json</code>, <code>policy.py</code> (PolicyChain), <code>toolkit_registry.py</code> + <code>toolkits.toml</code>, <code>computer_use.py</code></td></tr>
                <tr><td>MCP 클라이언트</td><td><code>core/mcp/</code></td><td><code>manager.py</code> (MCPServerManager), <code>stdio_client.py</code>, <code>registry.py</code>, 알림/캘린더 어댑터</td></tr>
                <tr><td>메모리</td><td><code>core/memory/</code></td><td><code>context.py</code> (ContextAssembler), <code>project.py</code>, <code>session_manager.py</code>, <code>episodic.py</code>, <code>recall_writer.py</code>, <code>user_profile.py</code></td></tr>
                <tr><td>스킬</td><td><code>core/skills/</code></td><td><code>skills.py</code> (레지스트리), <code>agents.py</code></td></tr>
                <tr><td>프롬프트</td><td><code>core/llm/prompts/</code></td><td><code>router.md</code>, <code>commentary.md</code>, <code>decomposer.md</code>, 해시 핀은 <code>__init__.py</code></td></tr>
                <tr><td>감사 추출</td><td><code>core/audit/</code></td><td><code>dim_extractor.py</code>, <code>manifest.py</code>, <code>eval_to_jsonl.py</code>, <code>contracts.py</code></td></tr>
                <tr><td>관측성</td><td><code>core/observability/</code></td><td><code>event_store.py</code>, <code>hook_persistence.py</code>, <code>run_log.py</code> (스케줄러 전용), <code>session_metrics.py</code>, <code>logging_config.py</code>, <code>transcript.py</code></td></tr>
                <tr><td>설정</td><td><code>core/config/</code></td><td><code>_settings.py</code>, <code>explain.py</code>, <code>env_io.py</code>, <code>routing.toml</code> + <code>routing_manifest.py</code>, <code>self_improving.py</code></td></tr>
                <tr><td>인증</td><td><code>core/auth/</code></td><td><code>oauth_login.py</code>, <code>profiles.py</code>, <code>rotation.py</code>, <code>cooldown.py</code></td></tr>
              </tbody>
            </table>

            <h2>Model</h2>
            <table>
              <thead><tr><th>서브시스템</th><th>루트</th><th>핵심 모듈</th></tr></thead>
              <tbody>
                <tr><td>라우터</td><td><code>core/llm/router/</code></td><td><code>calls/_route.py</code>, <code>calls/_failover.py</code>, <code>calls/{`{text,json,streaming,tools}`}.py</code></td></tr>
                <tr><td>어댑터</td><td><code>core/llm/adapters/</code></td><td><code>registry.py</code> (bootstrap_builtins), <code>dispatch.py</code></td></tr>
                <tr><td>프로바이더</td><td><code>core/llm/providers/</code></td><td><code>anthropic.py</code>, <code>openai.py</code>, <code>codex.py</code>, <code>glm.py</code></td></tr>
                <tr><td>지원 모듈</td><td><code>core/llm/</code></td><td><code>fallback.py</code>, <code>errors.py</code>, <code>token_tracker.py</code>, <code>model_pricing.toml</code>, <code>model_capabilities.py</code></td></tr>
              </tbody>
            </table>

            <h2>번들 플러그인</h2>
            <table>
              <thead><tr><th>플러그인</th><th>루트</th><th>핵심 모듈</th></tr></thead>
              <tbody>
                <tr><td>petri_audit</td><td><code>plugins/petri_audit/</code></td><td><code>cli_audit.py</code>, <code>runner.py</code>, <code>audit_mode.py</code>, <code>judge_dims/</code>, <code>seeds/</code></td></tr>
                <tr><td>seed_generation</td><td><code>plugins/seed_generation/</code></td><td><code>cli.py</code>, <code>orchestrator.py</code>, <code>tournament.py</code>, <code>agents/</code></td></tr>
              </tbody>
            </table>
          </>
        }
        en={
          <>
            <p>
              This page is a pure path inventory. For how the paths connect, see{" "}
              <a href="/geode/docs/develop/architecture">Architecture deep-dive</a>;
              for why the layers split this way, see{" "}
              <a href="/geode/docs/explanation/4-layer">Why five layers</a>.
            </p>

            <h2>Top-level entry modules</h2>
            <table>
              <thead><tr><th>Module</th><th>Role</th></tr></thead>
              <tbody>
                <tr><td><code>core/runtime.py</code></td><td><code>GeodeRuntime</code> bootstrap</td></tr>
                <tr><td><code>core/paths.py</code></td><td>Single resolution point for every directory path</td></tr>
                <tr><td><code>core/mcp_server.py</code></td><td><code>geode-mcp</code> entry point (stdio MCP server)</td></tr>
                <tr><td><code>core/async_runtime.py</code></td><td>Async event-loop helpers</td></tr>
              </tbody>
            </table>

            <h2>Self-Improving</h2>
            <table>
              <thead><tr><th>Subsystem</th><th>Root</th><th>Key modules</th></tr></thead>
              <tbody>
                <tr><td>Loop driver</td><td><code>core/self_improving/</code></td><td><code>train.py</code>, <code>campaign.py</code>, <code>prepare.py</code>, <code>program.md</code>, <code>watch_campaign.py</code></td></tr>
                <tr><td>Measurement gear</td><td><code>core/self_improving/</code></td><td><code>measure.py</code>, <code>fitness.py</code>, <code>gate.py</code>, <code>ledger.py</code></td></tr>
                <tr><td>Mutation runtime</td><td><code>core/self_improving/loop/</code></td><td><code>mutate/runner.py</code>, <code>mutate/policies.py</code>, <code>observe/baseline_epoch.py</code>, <code>inject/in_context_wiring.py</code>, <code>auto_trigger.py</code></td></tr>
              </tbody>
            </table>

            <h2>Agent</h2>
            <table>
              <thead><tr><th>Subsystem</th><th>Root</th><th>Key modules</th></tr></thead>
              <tbody>
                <tr><td>Agentic loop</td><td><code>core/agent/loop/</code></td><td><code>agent_loop.py</code> (AgenticLoop), <code>models.py</code>, <code>_context.py</code></td></tr>
                <tr><td>Sub-agents</td><td><code>core/agent/</code></td><td><code>sub_agent.py</code>, <code>worker.py</code>, <code>task_isolation.py</code></td></tr>
                <tr><td>System prompt</td><td><code>core/agent/</code></td><td><code>system_prompt.py</code>, <code>system_injection.py</code></td></tr>
                <tr><td>Guards</td><td><code>core/agent/</code></td><td><code>safety.py</code>, <code>budget.py</code>, <code>approval.py</code>, <code>context_manager.py</code></td></tr>
              </tbody>
            </table>

            <h2>Harness</h2>
            <table>
              <thead><tr><th>Subsystem</th><th>Root</th><th>Key modules</th></tr></thead>
              <tbody>
                <tr><td>Thin CLI</td><td><code>core/cli/</code></td><td><code>__init__.py</code> (Typer app), <code>commands/</code>, <code>routing.py</code>, <code>dispatcher.py</code>, <code>ipc_client.py</code>, <code>onboarding.py</code></td></tr>
                <tr><td>Serve daemon</td><td><code>core/server/</code></td><td><code>ipc_server/poller.py</code> (CLIPoller), <code>supervised/</code> (slack/discord/telegram pollers, webhook, services)</td></tr>
                <tr><td>Gateway</td><td><code>core/messaging/</code></td><td><code>binding.py</code> (ChannelManager), <code>models.py</code>, <code>slack_formatter.py</code></td></tr>
                <tr><td>Hooks</td><td><code>core/hooks/</code></td><td><code>system.py</code> (HookSystem + HookEvent), <code>dispatch.py</code>, <code>discovery.py</code></td></tr>
                <tr><td>Orchestration</td><td><code>core/orchestration/</code></td><td><code>lane_queue.py</code>, <code>task_system.py</code>, <code>compaction.py</code>, <code>tool_offload.py</code>, <code>isolated_execution.py</code></td></tr>
                <tr><td>Scheduler</td><td><code>core/scheduler/</code></td><td><code>service.py</code>, <code>triggers.py</code>, <code>nl_scheduler.py</code>, <code>jitter.py</code></td></tr>
                <tr><td>Wiring</td><td><code>core/wiring/</code></td><td><code>bootstrap.py</code>, <code>container.py</code>, <code>scheduling.py</code>, <code>startup.py</code></td></tr>
                <tr><td>Terminal UI</td><td><code>core/ui/</code></td><td><code>event_renderer.py</code>, <code>latex.py</code>, <code>console.py</code></td></tr>
              </tbody>
            </table>

            <h2>Runtime</h2>
            <table>
              <thead><tr><th>Subsystem</th><th>Root</th><th>Key modules</th></tr></thead>
              <tbody>
                <tr><td>Tools</td><td><code>core/tools/</code></td><td><code>registry.py</code>, <code>definitions.json</code>, <code>policy.py</code> (PolicyChain), <code>toolkit_registry.py</code> + <code>toolkits.toml</code>, <code>computer_use.py</code></td></tr>
                <tr><td>MCP client</td><td><code>core/mcp/</code></td><td><code>manager.py</code> (MCPServerManager), <code>stdio_client.py</code>, <code>registry.py</code>, notification/calendar adapters</td></tr>
                <tr><td>Memory</td><td><code>core/memory/</code></td><td><code>context.py</code> (ContextAssembler), <code>project.py</code>, <code>session_manager.py</code>, <code>episodic.py</code>, <code>recall_writer.py</code>, <code>user_profile.py</code></td></tr>
                <tr><td>Skills</td><td><code>core/skills/</code></td><td><code>skills.py</code> (registry), <code>agents.py</code></td></tr>
                <tr><td>Prompts</td><td><code>core/llm/prompts/</code></td><td><code>router.md</code>, <code>commentary.md</code>, <code>decomposer.md</code>; hash pins in <code>__init__.py</code></td></tr>
                <tr><td>Audit extraction</td><td><code>core/audit/</code></td><td><code>dim_extractor.py</code>, <code>manifest.py</code>, <code>eval_to_jsonl.py</code>, <code>contracts.py</code></td></tr>
                <tr><td>Observability</td><td><code>core/observability/</code></td><td><code>event_store.py</code>, <code>hook_persistence.py</code>, <code>run_log.py</code> (scheduler only), <code>session_metrics.py</code>, <code>logging_config.py</code>, <code>transcript.py</code></td></tr>
                <tr><td>Config</td><td><code>core/config/</code></td><td><code>_settings.py</code>, <code>explain.py</code>, <code>env_io.py</code>, <code>routing.toml</code> + <code>routing_manifest.py</code>, <code>self_improving.py</code></td></tr>
                <tr><td>Auth</td><td><code>core/auth/</code></td><td><code>oauth_login.py</code>, <code>profiles.py</code>, <code>rotation.py</code>, <code>cooldown.py</code></td></tr>
              </tbody>
            </table>

            <h2>Model</h2>
            <table>
              <thead><tr><th>Subsystem</th><th>Root</th><th>Key modules</th></tr></thead>
              <tbody>
                <tr><td>Router</td><td><code>core/llm/router/</code></td><td><code>calls/_route.py</code>, <code>calls/_failover.py</code>, <code>calls/{`{text,json,streaming,tools}`}.py</code></td></tr>
                <tr><td>Adapters</td><td><code>core/llm/adapters/</code></td><td><code>registry.py</code> (bootstrap_builtins), <code>dispatch.py</code></td></tr>
                <tr><td>Providers</td><td><code>core/llm/providers/</code></td><td><code>anthropic.py</code>, <code>openai.py</code>, <code>codex.py</code>, <code>glm.py</code></td></tr>
                <tr><td>Support</td><td><code>core/llm/</code></td><td><code>fallback.py</code>, <code>errors.py</code>, <code>token_tracker.py</code>, <code>model_pricing.toml</code>, <code>model_capabilities.py</code></td></tr>
              </tbody>
            </table>

            <h2>Bundled plugins</h2>
            <table>
              <thead><tr><th>Plugin</th><th>Root</th><th>Key modules</th></tr></thead>
              <tbody>
                <tr><td>petri_audit</td><td><code>plugins/petri_audit/</code></td><td><code>cli_audit.py</code>, <code>runner.py</code>, <code>audit_mode.py</code>, <code>judge_dims/</code>, <code>seeds/</code></td></tr>
                <tr><td>seed_generation</td><td><code>plugins/seed_generation/</code></td><td><code>cli.py</code>, <code>orchestrator.py</code>, <code>tournament.py</code>, <code>agents/</code></td></tr>
              </tbody>
            </table>
          </>
        }
      />
    </DocsShell>
  );
}
