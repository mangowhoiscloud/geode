import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "MCPMark filesystem/easy — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="benchmarks/mcpmark/filesystem-easy"
      title="MCPMark: filesystem/easy"
      titleKo="MCPMark: filesystem/easy"
      summary="Verifier-backed GEODE run record for MCPMark's filesystem easy subset with GPT-5.5 xhigh through the Codex subscription route."
      summaryKo="Codex subscription route의 GPT-5.5 xhigh로 실행한 MCPMark filesystem easy 하위 suite의 verifier-backed GEODE 실측 기록입니다."
    >
      <Bi
        ko={
          <>
            <h2>결과 요약</h2>
            <p>
              이 페이지는 GEODE가 MCPMark의 <code>filesystem/easy</code> 하위
              suite를 실행한 첫 공식 benchmark ledger입니다. 측정 대상은
              GEODE의 <code>AgenticLoop</code>, MCP filesystem server, Codex
              subscription route의 <code>gpt-5.5</code>, reasoning effort{" "}
              <code>xhigh</code> 조합입니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>항목</th>
                  <th>값</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Benchmark</td><td>MCPMark</td></tr>
                <tr><td>하위 suite</td><td><code>filesystem/easy</code></td></tr>
                <tr><td>Run date</td><td>2026-07-03</td></tr>
                <tr><td>Agent</td><td>GEODE local MCPMark adapter</td></tr>
                <tr><td>Model route</td><td>GEODE <code>gpt-5.5</code>, provider <code>openai-codex</code>, source <code>subscription</code></td></tr>
                <tr><td>Reasoning effort</td><td><code>xhigh</code></td></tr>
                <tr><td>Tasks</td><td>10</td></tr>
                <tr><td>Passed</td><td><strong>10 / 10</strong></td></tr>
                <tr><td>Accuracy</td><td><strong>100.0%</strong></td></tr>
                <tr><td>Total task execution time</td><td>1706.044s</td></tr>
                <tr><td>Average task execution time</td><td>170.604s</td></tr>
                <tr><td>Total agent execution time</td><td>1696.300s</td></tr>
                <tr><td>GEODE rounds</td><td>40 total / 4.0 average</td></tr>
                <tr><td>Token usage</td><td>234,483 input / 32,296 output / 266,779 total</td></tr>
              </tbody>
            </table>

            <h2>비교 가능성</h2>
            <p>
              이 수치는 MCPMark 전체 점수나 MCPMark Verified 점수가 아닙니다.
              <code>filesystem/easy</code>는 MCPMark의 가벼운 smoke/CI용 하위
              suite입니다. 따라서 이 결과는 GEODE의 MCPMark 연결, MCP dispatch,
              파일 시스템 작업 정확도, 장기 추론 비용을 보는 regression
              baseline으로 읽어야 합니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>비교 대상</th>
                  <th>판정</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>MCPMark <code>filesystem/easy</code></td><td>직접 비교 가능</td></tr>
                <tr><td>MCPMark Verified</td><td>직접 비교 불가. task set과 aggregation이 다름</td></tr>
                <tr><td>Agent-World Table 1의 MCP-Mark 평균</td><td>방향성 참고만 가능. benchmark version과 suite가 다름</td></tr>
                <tr><td>BFCL V4 / tau2-bench</td><td>별도 benchmark. 이 페이지의 수치와 평균내지 않음</td></tr>
              </tbody>
            </table>

            <h2>실행 명령</h2>
            <pre><code>{`cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp filesystem \\
  --task-suite easy \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 900 \\
  --exp-name geode-gpt55-xhigh-20260703-filesystem-easy \\
  --output-dir ./results-geode-live`}</code></pre>
            <p>
              <code>OPENAI_API_KEY=dummy</code>는 MCPMark pipeline의 환경변수
              존재 기대를 만족시키기 위한 placeholder입니다. 실제 모델 호출은
              GEODE의 <code>openai-codex</code> provider와{" "}
              <code>source=subscription</code> 경로를 사용했습니다. API key
              경로였다면 이 dummy 값으로는 인증되지 않습니다.
            </p>
            <p>
              Raw result artifact:
              <br />
              <code>artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-filesystem-easy/geode-gpt-5-5-xhigh__filesystem-easy/run-1</code>
            </p>

            <h2>Task별 결과</h2>
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Result</th>
                  <th>Time</th>
                  <th>Rounds</th>
                  <th>Tokens</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>file_context__file_splitting</code></td><td>PASS</td><td>640.287s</td><td>7</td><td>52,925</td></tr>
                <tr><td><code>file_context__pattern_matching</code></td><td>PASS</td><td>162.561s</td><td>3</td><td>24,781</td></tr>
                <tr><td><code>file_context__uppercase</code></td><td>PASS</td><td>145.404s</td><td>3</td><td>17,541</td></tr>
                <tr><td><code>file_property__largest_rename</code></td><td>PASS</td><td>61.050s</td><td>4</td><td>17,532</td></tr>
                <tr><td><code>file_property__txt_merging</code></td><td>PASS</td><td>124.666s</td><td>4</td><td>22,619</td></tr>
                <tr><td><code>folder_structure__structure_analysis</code></td><td>PASS</td><td>85.059s</td><td>3</td><td>12,977</td></tr>
                <tr><td><code>legal_document__file_reorganize</code></td><td>PASS</td><td>115.090s</td><td>5</td><td>24,307</td></tr>
                <tr><td><code>papers__papers_counting</code></td><td>PASS</td><td>113.489s</td><td>3</td><td>32,570</td></tr>
                <tr><td><code>student_database__duplicate_name</code></td><td>PASS</td><td>105.057s</td><td>3</td><td>20,720</td></tr>
                <tr><td><code>student_database__recommender_name</code></td><td>PASS</td><td>153.381s</td><td>5</td><td>40,807</td></tr>
              </tbody>
            </table>

            <h2>카테고리별 집계</h2>
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Tasks</th>
                  <th>Accuracy</th>
                  <th>Average time</th>
                  <th>Tokens</th>
                  <th>Average rounds</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>file_context</code></td><td>3</td><td>100.0%</td><td>316.08s</td><td>95,247</td><td>4.33</td></tr>
                <tr><td><code>file_property</code></td><td>2</td><td>100.0%</td><td>92.86s</td><td>40,151</td><td>4.00</td></tr>
                <tr><td><code>folder_structure</code></td><td>1</td><td>100.0%</td><td>85.06s</td><td>12,977</td><td>3.00</td></tr>
                <tr><td><code>legal_document</code></td><td>1</td><td>100.0%</td><td>115.09s</td><td>24,307</td><td>5.00</td></tr>
                <tr><td><code>papers</code></td><td>1</td><td>100.0%</td><td>113.49s</td><td>32,570</td><td>3.00</td></tr>
                <tr><td><code>student_database</code></td><td>2</td><td>100.0%</td><td>129.22s</td><td>61,527</td><td>4.00</td></tr>
              </tbody>
            </table>

            <h2>EOF offload 보정</h2>
            <p>
              이 run 전에 <code>read_multiple_files</code>의 display separator와
              trailing newline이 byte-for-byte verifier를 깨는 문제가 확인됐습니다.
              GEODE는 이를 모델 prompt에 맡기지 않고 MCP dispatch 계층에서
              보정합니다. 성공한 read 이후 local source EOF metadata를 캐시하고,
              같은 파일명으로 write할 때 source에 없던 display-induced trailing
              newline 하나만 제거합니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Smoke run</th>
                  <th>Result</th>
                  <th>Time</th>
                  <th>Rounds</th>
                  <th>Tool calls</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>EOF offload 전 <code>file_context/uppercase</code></td><td>1 / 1</td><td>398.6s</td><td>12</td><td>11</td></tr>
                <tr><td>EOF offload 후 <code>file_context/uppercase</code></td><td>1 / 1</td><td>167.9s</td><td>3</td><td>7</td></tr>
              </tbody>
            </table>

            <h2>판독</h2>
            <ul>
              <li>정확도는 이 하위 suite에서 포화입니다. 모든 verifier가 통과했습니다.</li>
              <li><code>xhigh</code> 설정의 wall time은 큽니다. 가장 느린 task는 <code>file_context__file_splitting</code>이며 640.287s가 걸렸습니다.</li>
              <li>평균 token 사용량은 task당 26,678 tokens입니다.</li>
              <li>현재 값은 smoke/regression baseline으로 적합하고, 비용 효율적인 PR 단위 CI gate로 쓰기에는 무겁습니다.</li>
            </ul>

            <h2>다음 측정</h2>
            <ul>
              <li>MCPMark Verified의 filesystem slice로 확장합니다.</li>
              <li>Notion, GitHub, Postgres, Playwright MCP server를 같은 GEODE adapter로 순차 연결합니다.</li>
              <li>BFCL V4와 tau2-bench는 별도 페이지로 분리해 route, user simulator, aggregation을 독립 기록합니다.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Result Summary</h2>
            <p>
              This page is GEODE&apos;s first official benchmark ledger for the
              MCPMark <code>filesystem/easy</code> subset. The measured system is
              GEODE&apos;s <code>AgenticLoop</code>, the MCP filesystem server,
              and <code>gpt-5.5</code> through the Codex subscription route with
              reasoning effort <code>xhigh</code>.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Benchmark</td><td>MCPMark</td></tr>
                <tr><td>Subset</td><td><code>filesystem/easy</code></td></tr>
                <tr><td>Run date</td><td>2026-07-03</td></tr>
                <tr><td>Agent</td><td>GEODE local MCPMark adapter</td></tr>
                <tr><td>Model route</td><td>GEODE <code>gpt-5.5</code>, provider <code>openai-codex</code>, source <code>subscription</code></td></tr>
                <tr><td>Reasoning effort</td><td><code>xhigh</code></td></tr>
                <tr><td>Tasks</td><td>10</td></tr>
                <tr><td>Passed</td><td><strong>10 / 10</strong></td></tr>
                <tr><td>Accuracy</td><td><strong>100.0%</strong></td></tr>
                <tr><td>Total task execution time</td><td>1706.044s</td></tr>
                <tr><td>Average task execution time</td><td>170.604s</td></tr>
                <tr><td>Total agent execution time</td><td>1696.300s</td></tr>
                <tr><td>GEODE rounds</td><td>40 total / 4.0 average</td></tr>
                <tr><td>Token usage</td><td>234,483 input / 32,296 output / 266,779 total</td></tr>
              </tbody>
            </table>

            <h2>Comparability</h2>
            <p>
              This is not a full MCPMark score and not a MCPMark Verified score.
              <code>filesystem/easy</code> is MCPMark&apos;s lightweight smoke/CI
              subset. Read it as a regression baseline for GEODE&apos;s MCPMark
              wiring, MCP dispatch, filesystem-task correctness, and long
              reasoning cost.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Comparator</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>MCPMark <code>filesystem/easy</code></td><td>Directly comparable</td></tr>
                <tr><td>MCPMark Verified</td><td>Not directly comparable. The task set and aggregation differ</td></tr>
                <tr><td>Agent-World Table 1 MCP-Mark average</td><td>Directional only. Benchmark version and suite differ</td></tr>
                <tr><td>BFCL V4 / tau2-bench</td><td>Different benchmarks. Do not average with this page&apos;s score</td></tr>
              </tbody>
            </table>

            <h2>Run Command</h2>
            <pre><code>{`cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp filesystem \\
  --task-suite easy \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 900 \\
  --exp-name geode-gpt55-xhigh-20260703-filesystem-easy \\
  --output-dir ./results-geode-live`}</code></pre>
            <p>
              <code>OPENAI_API_KEY=dummy</code> is a placeholder for the
              MCPMark pipeline environment-variable expectation. The actual
              model calls used the GEODE <code>openai-codex</code> provider with{" "}
              <code>source=subscription</code>. An API-key route would not have
              authenticated with the dummy value.
            </p>
            <p>
              Raw result artifact:
              <br />
              <code>artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-filesystem-easy/geode-gpt-5-5-xhigh__filesystem-easy/run-1</code>
            </p>

            <h2>Task Results</h2>
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Result</th>
                  <th>Time</th>
                  <th>Rounds</th>
                  <th>Tokens</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>file_context__file_splitting</code></td><td>PASS</td><td>640.287s</td><td>7</td><td>52,925</td></tr>
                <tr><td><code>file_context__pattern_matching</code></td><td>PASS</td><td>162.561s</td><td>3</td><td>24,781</td></tr>
                <tr><td><code>file_context__uppercase</code></td><td>PASS</td><td>145.404s</td><td>3</td><td>17,541</td></tr>
                <tr><td><code>file_property__largest_rename</code></td><td>PASS</td><td>61.050s</td><td>4</td><td>17,532</td></tr>
                <tr><td><code>file_property__txt_merging</code></td><td>PASS</td><td>124.666s</td><td>4</td><td>22,619</td></tr>
                <tr><td><code>folder_structure__structure_analysis</code></td><td>PASS</td><td>85.059s</td><td>3</td><td>12,977</td></tr>
                <tr><td><code>legal_document__file_reorganize</code></td><td>PASS</td><td>115.090s</td><td>5</td><td>24,307</td></tr>
                <tr><td><code>papers__papers_counting</code></td><td>PASS</td><td>113.489s</td><td>3</td><td>32,570</td></tr>
                <tr><td><code>student_database__duplicate_name</code></td><td>PASS</td><td>105.057s</td><td>3</td><td>20,720</td></tr>
                <tr><td><code>student_database__recommender_name</code></td><td>PASS</td><td>153.381s</td><td>5</td><td>40,807</td></tr>
              </tbody>
            </table>

            <h2>Category Rollup</h2>
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Tasks</th>
                  <th>Accuracy</th>
                  <th>Average time</th>
                  <th>Tokens</th>
                  <th>Average rounds</th>
                </tr>
              </thead>
              <tbody>
                <tr><td><code>file_context</code></td><td>3</td><td>100.0%</td><td>316.08s</td><td>95,247</td><td>4.33</td></tr>
                <tr><td><code>file_property</code></td><td>2</td><td>100.0%</td><td>92.86s</td><td>40,151</td><td>4.00</td></tr>
                <tr><td><code>folder_structure</code></td><td>1</td><td>100.0%</td><td>85.06s</td><td>12,977</td><td>3.00</td></tr>
                <tr><td><code>legal_document</code></td><td>1</td><td>100.0%</td><td>115.09s</td><td>24,307</td><td>5.00</td></tr>
                <tr><td><code>papers</code></td><td>1</td><td>100.0%</td><td>113.49s</td><td>32,570</td><td>3.00</td></tr>
                <tr><td><code>student_database</code></td><td>2</td><td>100.0%</td><td>129.22s</td><td>61,527</td><td>4.00</td></tr>
              </tbody>
            </table>

            <h2>EOF Offload</h2>
            <p>
              Before this run, <code>read_multiple_files</code> display
              separators and trailing newlines were found to break
              byte-for-byte verifier checks. GEODE now handles that in the MCP
              dispatch layer instead of relying on the model prompt. After a
              successful read, GEODE caches local source EOF metadata and trims
              one display-induced trailing newline on same-name writes when the
              source file did not have one.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Smoke run</th>
                  <th>Result</th>
                  <th>Time</th>
                  <th>Rounds</th>
                  <th>Tool calls</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Before EOF offload, <code>file_context/uppercase</code></td><td>1 / 1</td><td>398.6s</td><td>12</td><td>11</td></tr>
                <tr><td>After EOF offload, <code>file_context/uppercase</code></td><td>1 / 1</td><td>167.9s</td><td>3</td><td>7</td></tr>
              </tbody>
            </table>

            <h2>Reading</h2>
            <ul>
              <li>Accuracy is saturated on this subset. Every verifier passed.</li>
              <li><code>xhigh</code> wall time is high. The slowest task was <code>file_context__file_splitting</code> at 640.287s.</li>
              <li>Average token usage is 26,678 tokens per task.</li>
              <li>This is a good smoke/regression baseline, but too heavy for a cost-efficient per-PR CI gate.</li>
            </ul>

            <h2>Next Measurements</h2>
            <ul>
              <li>Extend to the MCPMark Verified filesystem slice.</li>
              <li>Attach Notion, GitHub, Postgres, and Playwright MCP servers through the same GEODE adapter.</li>
              <li>Record BFCL V4 and tau2-bench on separate pages, with independent route, user-simulator, and aggregation fields.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
