import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Lineage and positioning — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/lineage"
      title="Lineage and positioning"
      titleKo="계보와 좌표"
      summary="Where this loop sits in the self-evolving agents literature. An honest recombination of known parts, not a new primitive."
      summaryKo="이 루프가 self-evolving agents 문헌에서 어디에 위치하는지 짚습니다. 새로운 primitive가 아니라, 알려진 조각들을 정직하게 재조합한 결과입니다."
    >
      <Bi
        ko={
          <>
            <h2>한 문장 주장</h2>
            <p>
              GEODE의 자기개선 루프는 새로운 알고리즘이 아닙니다. self-evolving
              agents라는 잘 정립된 계보 위에 있고, GEODE의 기여는 그 계보를 다른
              목표로 다시 겨눈 것, 그리고 알려진 조각들을 새로 조합한 것입니다.
              이 페이지는 그 계보를 정직하게 짚고, GEODE가 어디서 갈라져 나왔는지
              밝힙니다.
            </p>
            <p>
              두 루프의 구조 자체가 처음이라면{" "}
              <a href="/geode/docs/concepts/two-loops">두 개의 루프</a>를 먼저
              읽으세요. 바깥쪽 루프의 전체 흐름은{" "}
              <a href="/geode/docs/capabilities/autoresearch">폐루프</a>에
              있습니다.
            </p>

            <h2>계보는 이미 잘 정립되어 있다</h2>
            <p>
              에이전트가 스스로를 고치는 연구는 2022년부터 꾸준히 쌓였습니다.
              무엇이 진화하는지, 무엇을 fitness로 삼는지, 어떤 탐색 방식을 쓰는지
              기준으로 정리하면 다음과 같습니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>시기</th>
                  <th>시스템</th>
                  <th>진화 대상 / fitness / 탐색</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>2022</td>
                  <td>APE</td>
                  <td>프롬프트 / 정확도 / 탐색</td>
                </tr>
                <tr>
                  <td>2023</td>
                  <td>OPRO, Promptbreeder, STOP, Reflexion, Voyager</td>
                  <td>프롬프트와 코드 / 정확도와 효용 / 진화와 재귀</td>
                </tr>
                <tr>
                  <td>2024</td>
                  <td>
                    ADAS (Meta Agent Search), Gödel Agent, TextGrad, DSPy-MIPRO,
                    Rainbow Teaming
                  </td>
                  <td>코드와 프롬프트 / 벤치마크 / 아카이브와 재귀적 자기수정</td>
                </tr>
                <tr>
                  <td>2025 상반기</td>
                  <td>SICA, AlphaEvolve, Darwin Gödel Machine (DGM), SEAL</td>
                  <td>자기 코드와 알고리즘 / SWE-bench와 알고리즘 / 아카이브</td>
                </tr>
                <tr>
                  <td>2025 하반기</td>
                  <td>
                    GEPA (ICLR 2026 oral), A Survey of Self-Evolving Agents,
                    EvolveR
                  </td>
                  <td>프롬프트와 경험 / 정확도 / Pareto frontier</td>
                </tr>
                <tr>
                  <td>2026 상반기</td>
                  <td>survey 통합 단계</td>
                  <td>
                    분야 이름이 self-evolving agents로 굳고, parametric(가중치)
                    진화와 non-parametric(프롬프트, 메모리, 도구, scaffolding)
                    진화로 갈림
                  </td>
                </tr>
              </tbody>
            </table>
            <p>
              요점은 단순합니다. 이 줄기는 4년 넘게 이어졌고, GEODE는 그 줄기의
              가장 최근 가지 하나입니다.
            </p>

            <h2>두 갈래, 그리고 비어 있는 칸</h2>
            <p>
              위 계보를 두 축으로 나눠 보면 분야의 무게중심이 드러납니다. 한 축은
              fitness가 무엇인가(능력인가 안전인가), 다른 축은 무엇을 바꾸는가
              (scaffolding인가 가중치인가)입니다.
            </p>
            <ul>
              <li>
                scaffolding을 건드리는 시스템(DGM, ADAS, STOP, Promptbreeder,
                GEPA, AlphaEvolve, SICA)은 대부분 <strong>능력</strong>을
                최적화합니다. SWE-bench, 알고리즘, 정확도가 그 대상입니다.
              </li>
              <li>
                fitness가 <strong>안전</strong>인 시스템(Constitutional AI, MART,
                Self-MOA)은 대부분 <strong>가중치</strong>를 갱신합니다.
              </li>
            </ul>
            <p>
              그러면 한 칸이 비어 있습니다. fitness가 안전이면서, 가중치를 건드리지
              않고 scaffolding만 바꾸는 칸입니다. 2026년 5월 기준으로 이 칸은 거의
              비어 있습니다.
            </p>
            <pre>{`                 fitness = 능력            fitness = 안전
scaffolding   DGM, ADAS, STOP,        <- 거의 비어 있음
(가중치 X)    GEPA, AlphaEvolve, SICA     (GEODE가 겨누는 칸)

가중치 갱신   (RLHF 계열)              Constitutional AI, MART, Self-MOA`}</pre>

            <h2>GEODE = DGM에 세 가지 치환</h2>
            <p>
              GEODE를 한 줄로 쓰면 이렇습니다. DGM의 루프를 가져오되 세 군데를
              바꿨습니다.
            </p>
            <ol>
              <li>
                <strong>능력 벤치마크 fitness → 적대적 안전 감사 fitness</strong>.
                SWE-bench 점수 대신 Petri 등급의 다차원 안전 감사로 평가합니다.
              </li>
              <li>
                <strong>open-ended 아카이브 → 정직한 (1+1) 챔피언 체인</strong>.
                다양한 frontier를 유지하는 대신, critical dimension에 거부권을 둔
                단일 챔피언 계보를 이어갑니다.
              </li>
              <li>
                <strong>고정 벤치마크 → 공진화하는 적대적 seed</strong>.
                co-scientist seed 생성 파이프라인이 에이전트와 나란히 테스트
                분포를 키웁니다.
              </li>
            </ol>
            <p>
              그리고 한 가지 더. GEODE는 non-parametric입니다. scaffolding만
              바꿉니다. 변이 표면은 7개 behaviour kinds, 곧 프롬프트 섹션, 도구
              정책, 분해 방식, reflection, skill 카탈로그, 에이전트 contract,
              도구 설명이며, 가중치는 절대 건드리지 않습니다.
            </p>
            <p>
              이 치환들이 코드에서 어떻게 도는지는{" "}
              <a href="/geode/docs/capabilities/autoresearch">폐루프</a>에서,
              감사에 쓰는 평가 프레임워크는{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>에서 다룹니다.
            </p>

            <h2>가장 가까운 선행 시스템</h2>
            <table>
              <thead>
                <tr>
                  <th>시스템</th>
                  <th>GEODE가 가져온 것</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>DGM</td>
                  <td>루프 구조와 scaffolding을 바꾸는 substrate</td>
                </tr>
                <tr>
                  <td>GEPA</td>
                  <td>
                    reflective single-mutation 방식, 그리고 가중치 없는 프롬프트
                    진화가 RL을 이길 수 있다는 최근의 가장 강한 증거
                  </td>
                </tr>
                <tr>
                  <td>Rainbow Teaming + Petri</td>
                  <td>공진화하는 적대적 seed와 다차원 안전 감사</td>
                </tr>
              </tbody>
            </table>
            <p>
              여기서 정직하게 밝혀 둘 점이 둘 있습니다. Rainbow Teaming은 적대적
              프롬프트를 공진화시키지만 공격 생성에서 멈춥니다. 그 seed를 다시
              방어자의 scaffolding 개선으로 돌려보내지는 않습니다. Petri는 측정만
              합니다.
            </p>

            <h2>정직한 단서</h2>
            <blockquote>
              <p>
                <strong>비어 있는 칸은 증거의 부재이지 부재의 증거가 아닙니다.</strong>{" "}
                2026년 5월 문헌 검색 범위에서 보이지 않았다는 뜻이지, 존재하지
                않는다고 증명된 것은 아닙니다.
              </p>
              <p>
                <strong>GEODE는 frontier의 수렴 방향에서 일부러 벗어났습니다.</strong>{" "}
                GEPA, DGM, SICA, ADAS는 Pareto frontier나 open-ended 아카이브로
                수렴합니다. 이들이 다양한 frontier를 유지하는 이유는 비용 때문입니다.
                값싼 task 지표 위에서, 노이즈가 섞인 단일 평가 신호를 견디려고
                frontier를 넓게 둡니다. GEODE는 값비싸고 노이즈가 큰 안전 감사
                위에서 돌기 때문에 frugal한 (1+1)을 택했습니다. 공짜로 얻는
                이득이 아니라 실제 trade-off입니다. 아카이브 유지는 앞으로 열어
                둘 설계 방향입니다.
              </p>
              <p>
                <strong>GEODE는 알려진 조각들의 재조합입니다.</strong>{" "}
                scaffolding 자기수정은 STOP과 DGM에서, reflective single-mutation은
                GEPA와 TextGrad에서, 공진화 seed는 Rainbow Teaming에서, 감사는
                Petri에서, 안전 목표는 Constitutional AI에서 가져왔습니다. 어느 한
                재료의 신규성을 주장하는 것은 부정확합니다.
              </p>
            </blockquote>

            <h2>출처</h2>
            <ul>
              <li>Darwin Gödel Machine (arXiv:2505.22954)</li>
              <li>ADAS / Meta Agent Search (arXiv:2408.08435)</li>
              <li>Promptbreeder (arXiv:2309.16797)</li>
              <li>STOP: Self-Taught Optimizer (arXiv:2310.02304)</li>
              <li>AlphaEvolve (arXiv:2506.13131)</li>
              <li>SICA (arXiv:2504.15228)</li>
              <li>GEPA (arXiv:2507.19457)</li>
              <li>A Survey of Self-Evolving Agents (arXiv:2507.21046)</li>
              <li>Gödel Agent (arXiv:2410.04444)</li>
              <li>EvolveR (arXiv:2510.16079)</li>
              <li>Rainbow Teaming (arXiv:2402.16822)</li>
              <li>MART (arXiv:2311.07689)</li>
              <li>Anthropic, Building and evaluating alignment auditing agents</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>The one-sentence claim</h2>
            <p>
              GEODE&apos;s self-improving loop is not a new algorithm. It sits on
              a well-established lineage called self-evolving agents, and
              GEODE&apos;s contribution is re-aiming that lineage at a different
              objective and recombining known parts. This page traces the lineage
              honestly and says where GEODE branched from it.
            </p>
            <p>
              If the two-loop structure itself is new to you, read{" "}
              <a href="/geode/docs/concepts/two-loops">The two loops</a> first,
              and{" "}
              <a href="/geode/docs/capabilities/autoresearch">The closed loop</a>{" "}
              for the outer loop end to end. This page reads better after them.
            </p>

            <h2>The lineage is well-established</h2>
            <p>
              Work on agents that fix themselves has accumulated steadily since
              2022. Organized by what evolves, what serves as fitness, and what
              kind of search is used, it looks like this.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Systems</th>
                  <th>What evolves / fitness / search</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>2022</td>
                  <td>APE</td>
                  <td>prompt / accuracy / search</td>
                </tr>
                <tr>
                  <td>2023</td>
                  <td>OPRO, Promptbreeder, STOP, Reflexion, Voyager</td>
                  <td>prompt and code / accuracy and utility / evolution and recursion</td>
                </tr>
                <tr>
                  <td>2024</td>
                  <td>
                    ADAS (Meta Agent Search), Gödel Agent, TextGrad, DSPy-MIPRO,
                    Rainbow Teaming
                  </td>
                  <td>code and prompt / benchmark / archive and recursive self-mod</td>
                </tr>
                <tr>
                  <td>2025 H1</td>
                  <td>SICA, AlphaEvolve, Darwin Gödel Machine (DGM), SEAL</td>
                  <td>self-code and algorithms / SWE-bench and algorithms / archive</td>
                </tr>
                <tr>
                  <td>2025 H2</td>
                  <td>
                    GEPA (ICLR 2026 oral), A Survey of Self-Evolving Agents,
                    EvolveR
                  </td>
                  <td>prompt and experience / accuracy / Pareto frontier</td>
                </tr>
                <tr>
                  <td>2026 H1</td>
                  <td>survey consolidation</td>
                  <td>
                    the field is now named self-evolving agents, split into
                    parametric (weight) and non-parametric (prompt, memory, tools,
                    scaffolding) evolution
                  </td>
                </tr>
              </tbody>
            </table>
            <p>
              The point is simple. This line has run for more than four years, and
              GEODE is one of its most recent branches.
            </p>

            <h2>Two families, and the empty cell</h2>
            <p>
              Split that lineage along two axes and the field&apos;s center of
              gravity shows. One axis is what fitness is (capability or safety),
              the other is what gets changed (scaffolding or weights).
            </p>
            <ul>
              <li>
                Systems that touch scaffolding (DGM, ADAS, STOP, Promptbreeder,
                GEPA, AlphaEvolve, SICA) mostly optimize{" "}
                <strong>capability</strong>. SWE-bench, algorithms, accuracy.
              </li>
              <li>
                Systems whose fitness is <strong>safety</strong> (Constitutional
                AI, MART, Self-MOA) mostly update <strong>weights</strong>.
              </li>
            </ul>
            <p>
              That leaves one cell open. The cell where fitness is safety, no
              weight update happens, and only the scaffolding changes. As of
              2026-05 that cell is nearly empty.
            </p>
            <pre>{`                  fitness = capability       fitness = safety
scaffolding    DGM, ADAS, STOP,          <- nearly empty
(no weights)   GEPA, AlphaEvolve, SICA      (the cell GEODE aims at)

weight update  (RLHF family)             Constitutional AI, MART, Self-MOA`}</pre>

            <h2>GEODE = DGM with three substitutions</h2>
            <p>
              Stated plainly: GEODE takes the DGM loop and changes three places.
            </p>
            <ol>
              <li>
                <strong>capability benchmark fitness to adversarial safety-audit
                fitness</strong>. Instead of a SWE-bench score, it scores with a
                Petri-grade, multi-dimensional safety audit.
              </li>
              <li>
                <strong>open-ended archive to an honest (1+1) champion chain</strong>.
                Rather than keeping a diverse frontier, it carries a single
                champion lineage with a critical-dimension veto.
              </li>
              <li>
                <strong>fixed benchmark to co-evolved adversarial seeds</strong>.
                A co-scientist seed-generation pipeline grows the test
                distribution alongside the agent.
              </li>
            </ol>
            <p>
              And one more thing. GEODE is non-parametric. It mutates scaffolding
              only, across seven behaviour kinds: prompt sections, tool policy,
              decomposition, reflection, the skill catalog, agent contracts, and
              tool descriptions. Never weights.
            </p>
            <p>
              For how these substitutions run in code, see{" "}
              <a href="/geode/docs/capabilities/autoresearch">The closed loop</a>.
              For the evaluation framework that does the auditing, see{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>.
            </p>

            <h2>Closest prior systems</h2>
            <table>
              <thead>
                <tr>
                  <th>System</th>
                  <th>What GEODE took from it</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>DGM</td>
                  <td>the loop, and the scaffolding substrate it mutates</td>
                </tr>
                <tr>
                  <td>GEPA</td>
                  <td>
                    the reflective single-mutation mechanism, and the strongest
                    recent evidence that no-weights prompt evolution can beat RL
                  </td>
                </tr>
                <tr>
                  <td>Rainbow Teaming + Petri</td>
                  <td>co-evolved adversarial seeds and a multi-dimensional safety audit</td>
                </tr>
              </tbody>
            </table>
            <p>
              Two honest notes here. Rainbow Teaming co-evolves adversarial
              prompts but stops at attack generation. It does not feed those seeds
              back to improve the defender&apos;s scaffolding. Petri is
              measurement-only.
            </p>

            <h2>Honest caveats</h2>
            <blockquote>
              <p>
                <strong>The empty cell is absence of evidence, not evidence of
                absence.</strong>{" "}
                It means nothing showed up within a 2026-05 literature search, not
                that nothing exists.
              </p>
              <p>
                <strong>GEODE deliberately diverges from the frontier&apos;s
                convergence.</strong>{" "}
                GEPA, DGM, SICA, and ADAS converge on Pareto frontiers and
                open-ended archives. They keep a diverse frontier for a reason: to
                stay robust to noisy single-eval signals, on cheap task metrics.
                GEODE runs on an expensive, noisy safety audit, so it chose a
                frugal (1+1). This is a real trade-off, not a free win.
                Archive-keep is a future design avenue.
              </p>
              <p>
                <strong>GEODE is a recombination of known parts.</strong>{" "}
                Scaffolding self-mod comes from STOP and DGM, reflective
                single-mutation from GEPA and TextGrad, co-evolved seeds from
                Rainbow Teaming, the audit from Petri, the safety objective from
                Constitutional AI. Claiming novelty of any single ingredient would
                be inaccurate.
              </p>
            </blockquote>

            <h2>Sources</h2>
            <ul>
              <li>Darwin Gödel Machine (arXiv:2505.22954)</li>
              <li>ADAS / Meta Agent Search (arXiv:2408.08435)</li>
              <li>Promptbreeder (arXiv:2309.16797)</li>
              <li>STOP: Self-Taught Optimizer (arXiv:2310.02304)</li>
              <li>AlphaEvolve (arXiv:2506.13131)</li>
              <li>SICA (arXiv:2504.15228)</li>
              <li>GEPA (arXiv:2507.19457)</li>
              <li>A Survey of Self-Evolving Agents (arXiv:2507.21046)</li>
              <li>Gödel Agent (arXiv:2410.04444)</li>
              <li>EvolveR (arXiv:2510.16079)</li>
              <li>Rainbow Teaming (arXiv:2402.16822)</li>
              <li>MART (arXiv:2311.07689)</li>
              <li>Anthropic, Building and evaluating alignment auditing agents</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
