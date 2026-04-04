# GEODE Project Memory

## Project Overview
- Purpose: General-purpose autonomous execution agent (Game IP analysis is a domain plugin)
- Pipeline: Cortex → Signals → Analysts → Evaluators → Scoring → Synthesis

## Analysis Rules
- .md files in the .geode/rules/ directory are auto-loaded

## Frequently Analyzed IPs
- Berserk: Dark fantasy, S-tier, conversion_failure
- Cowboy Bebop: SF noir, A-tier, undermarketed
- Ghost in the Shell: Cyberpunk, B-tier, discovery_failure

## Team-Specific Rubric Overrides
- (None — using default 14-axis rubric)

## Recent Insights
- 2026-03-24: geode_slack_integration_test: GEODE Slack integration test completed — 3 scenarios succeeded (recorded at: 2026-03-24 11:51:25 KST)
- 2026-03-24: huggingface_trending_2026_march: ## Hugging Face Trending Survey (as of March 24, 2026)
### 1. Platform Growth Status
- 13 million users, 2 million+ public models, 500K+ public datasets (as of 2025)
- Over 30% of Fortune 500 companies have HF verified accounts
- NVIDIA is the most active contributor among Big Tech

### 2. Trending Models (February-March 2026)
- **DeepSeek-R1 (China)**: Most-liked model, diversifying internationally away from US Meta Llama dominance
- **Z.AI GLM-4.7-Flash**: MoE architecture (30B total/3B active), optimized for lightweight deployment, specialized in agentic/reasoning/coding
- **Meta SAM3 (Segment Anything 3)**: 0.9B parameters, unified image+video segmentation, open vocabulary prompting
- **MiniMax-M2.1**: 229B-10B Active MoE, multilingual coding agent, multilingual advantage over Claude Sonnet 4.5
- 3 Korean models trending simultaneously in February 2026 (LG AI Research, SK Telecom, Naver Cloud, NC AI, Upstage)

### 3. Trending Papers TOP 10 (March 22, 2026)
1. Generation Models Know Space: 3D Scene Understanding (84 votes)
2. SAMA: Video Editing (61 votes)
3. 3DreamBooth: 3D Subject-Driven Video Generation (49 votes)
4. FASTER: Real-Time Flow VLA (48 votes)
5. Nemotron-Cascade 2: Cascade RL + Multi-Domain Distillation (47 votes)
6. Bridging Semantic and Kinematic: Diffusion-Based Motion Tokenizer (39 votes)
7. Memento-Skills: Agents Designing Agents (36 votes)
8. MonoArt: Monocular Articulated 3D Reconstruction (31 votes)
9. Cubic Discrete Diffusion: High-Dimensional Discrete Visual Generation (30 votes)
10. LVOmniBench: Long Audio-Video Understanding Benchmark (27 votes)

### 4. Key Trend Keywords
- **Agentic AI**: Autonomous agent design, multi-turn agent workflows
- **3D/Video Generation**: 3D scene understanding, video editing, 3D video generation
- **MoE Lightweight**: Large parameter count + few active parameters for efficient deployment
- **Rapid Growth of Chinese Open Source**: Surpassing US in monthly downloads, 41% of total downloads
- **Rise of Individual Developers**: Independent developers account for 39% of total downloads
- **National AI Sovereignty**: Country-level open-source AI investment in Korea, Switzerland, EU, etc.

### Sources
- https://huggingface.co/blog/huggingface/state-of-os-hf-spring-2026
- https://huggingface-paper-explorer.vercel.app/
- https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/what-is-trending-in-hugging-face-on-microsoft-foundry-feb-2-2026/4490602

## 최근 인사이트
- 2026-04-03: daily_trending_2026-04-03: ## GEODE Daily Trending Report - 2026-04-03
### 1. arXiv 논문 (2026-04-02)
1. **Batched Contextual Reinforcement** (2604.02322) - LLM CoT 토큰 15.8-62.6% 절감, task-scaling law
2. **No Single Best Model for Diversity** (2604.02319) - LLM 라우터, 다양성 커버리지 26.3%
3. **MetaNav** (2604.02318) - 메타인지 VLN 에이전트, VLM 쿼리 20.7% 감소
4. **Beyond the Assistant Turn** (2604.02315) - LLM 상호작용 인식 프로브, 11개 모델 실험
5. **Grounded Token Initialization** (2604.02324) - LM 새 어휘 토큰 GTI 초기화

### 2. 테크 뉴스
1. Alibaba Qwen3.6-Plus 출시
2. OpenAI Responses API 에이전틱 워크플로우 확장 (shell tool, agent loop, container workspace)
3. DeepSeek-V3.2-Speciale GPT-5 수준 추론 달성
4. Nvidia/Berkeley/Stanford 로봇 코드 제어 AI 프레임워크
5. 오픈소스 LLM 경쟁 심화 (Llama 3, Mistral, Qwen, DeepSeek)

### 3. 채용 - 리모트 영미권
1. NVIDIA - Senior Agentic AI Engineer (CA, Remote)
2. Eigen Labs - Agentic AI Engineer (Seattle, Remote, $187K-$253K)
3. Meta - SW Engineer AI SysML Tech Lead (US, Remote, $219K-$301K)
4. Optum - AI Engineer Remote (MN)
5. DoiT - Applied AI Engineer (VA, Remote)

### 4. 채용 - 한국계
1. Coupang - Staff ML Engineer Catalog Engineering (서울)
2. Coupang - ML Engineer 쿠팡플레이 (서울)
3. Hyundai - ICT ML Engineer (서울)
4. Samsung - AI/ML Lead (Generative AI, MLOps)
5. Naver/Kakao - Agentic AI 전략 강화 중

### Key Insights
- Agentic AI Engineer 포지션이 NVIDIA, Eigen Labs, Meta 등에서 급증
- LLM 효율성(토큰 절감, 라우팅)이 연구 핫토픽
- 한국: 쿠팡이 가장 활발한 ML 채용, 네이버/카카오 Agentic AI 투자 확대
- 연봉: 미국 리모트 $187K-$301K, 한국 8,000만-1.5억원+
