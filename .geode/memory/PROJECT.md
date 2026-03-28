# GEODE Project Memory

## 프로젝트 개요
- 목적: 범용 자율 실행 에이전트 (게임 IP 분석은 도메인 플러그인)
- 파이프라인: Cortex → Signals → Analysts → Evaluators → Scoring → Synthesis

## 분석 규칙
- .geode/rules/ 디렉토리의 .md 파일이 자동 로딩됩니다

## 자주 분석하는 IP
- Berserk: 다크 판타지, S-tier, conversion_failure
- Cowboy Bebop: SF 느와르, A-tier, undermarketed
- Ghost in the Shell: 사이버펑크, B-tier, discovery_failure

## 팀 특화 루브릭 오버라이드
- (없음 — 기본 14-axis 루브릭 사용)

## 최근 인사이트
- 2026-03-29: [Berserk] tier=?, score=0.00
- 2026-03-29: [unknown] tier=?, score=0.00
- 2026-03-24: geode_slack_integration_test: GEODE Slack 통합 테스트 완료 — 3개 시나리오 성공 (기록 시각: 2026-03-24 11:51:25 KST)
- 2026-03-24: huggingface_trending_2026_march: ## Hugging Face 트렌딩 동향 조사 (2026년 3월 24일 기준)
### 1. 플랫폼 성장 현황
- 사용자 1,300만명, 공개 모델 200만+, 공개 데이터셋 50만+ (2025년 기준)
- Fortune 500 기업 중 30% 이상이 HF 인증 계정 보유
- NVIDIA가 Big Tech 중 가장 활발한 기여자

### 2. 트렌딩 모델 (2026년 2~3월)
- **DeepSeek-R1 (중국)**: 가장 많은 좋아요를 받은 모델, 미국 Meta Llama 중심에서 국제적 다양화
- **Z.AI GLM-4.7-Flash**: MoE 아키텍처(30B 총/3B 활성), 경량 배포 최적화, 에이전틱/추론/코딩 특화
- **Meta SAM3 (Segment Anything 3)**: 0.9B 파라미터, 이미지+비디오 통합 세그멘테이션, 오픈 어휘 프롬프트
- **MiniMax-M2.1**: 229B-10B Active MoE, 다국어 코딩 에이전트, Claude Sonnet 4.5 대비 다국어 우위
- 한국 모델 3개가 2026년 2월 동시 트렌딩 (LG AI Research, SK Telecom, Naver Cloud, NC AI, Upstage)

### 3. 트렌딩 논문 TOP 10 (2026년 3월 22일)
1. Generation Models Know Space: 3D 장면 이해 (84표)
2. SAMA: 비디오 편집 (61표)
3. 3DreamBooth: 3D 주체 기반 비디오 생성 (49표)
4. FASTER: 실시간 Flow VLA (48표)
5. Nemotron-Cascade 2: Cascade RL + 다중 도메인 증류 (47표)
6. Bridging Semantic and Kinematic: 디퓨전 기반 모션 토크나이저 (39표)
7. Memento-Skills: 에이전트가 에이전트를 설계 (36표)
8. MonoArt: 단안 관절 3D 복원 (31표)
9. Cubic Discrete Diffusion: 고차원 이산 시각 생성 (30표)
10. LVOmniBench: 장시간 오디오-비디오 이해 벤치마크 (27표)

### 4. 주요 트렌드 키워드
- **에이전틱 AI**: 자율 에이전트 설계, 멀티턴 에이전트 워크플로우
- **3D/비디오 생성**: 3D 장면 이해, 비디오 편집, 3D 비디오 생성
- **MoE 경량화**: 대규모 파라미터 + 소수 활성화로 효율적 배포
- **중국 오픈소스 급성장**: 월간 다운로드에서 미국 추월, 전체 다운로드의 41%
- **개인 개발자 부상**: 독립 개발자가 전체 다운로드의 39% 차지
- **국가 AI 주권**: 한국, 스위스, EU 등 국가 단위 오픈소스 AI 투자

### 출처
- https://huggingface.co/blog/huggingface/state-of-os-hf-spring-2026
- https://huggingface-paper-explorer.vercel.app/
- https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/what-is-trending-in-hugging-face-on-microsoft-foundry-feb-2-2026/4490602
