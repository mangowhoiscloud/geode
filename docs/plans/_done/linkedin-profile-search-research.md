# LinkedIn 프로필 검색 MCP 리서치 (2026-03-15)

## 결론

**`stickerdaniel/linkedin-mcp-server`** (1K+ stars) 채택. `uvx linkedin-scraper-mcp`로 설치하며, 브라우저 기반으로 API 키 없이 타인 프로필 검색 가능.

## 후보 비교

| 방안 | 타인 검색 | 비용 | 설치 난이도 | 안정성 |
|------|----------|------|-----------|--------|
| **stickerdaniel/linkedin-mcp-server** | O (`search_people`, `get_person_profile`) | 무료 | `uvx` 1줄 | 중 (브라우저 기반) |
| proxycurl_mcp (EnrichLayer) | O (7개 도구) | $588/yr~ | npm + API 키 | 높음 |
| RapidAPI MCP | O | $0-50/mo | npm + API 키 | 중 |
| Bright Data MCP | 포스트만 | 무료 5K/mo | npm + API 키 | 높음 |
| linkedin-mcp-runner (LiGo) | X (자기 콘텐츠만) | 무료 | npx | 높음 |
| Chrome MCP (기존) | O (수동) | 무료 | 이미 설치 | 낮음 |
| Brave Search + site:linkedin.com | 부분 (스니펫만) | 무료 | 이미 구현 | 높음 |

## stickerdaniel/linkedin-mcp-server 상세

- **GitHub**: github.com/stickerdaniel/linkedin-mcp-server (1,042 stars)
- **설치**: `uvx linkedin-scraper-mcp --login` (첫 실행 시 브라우저 로그인)
- **세션**: `~/.linkedin-mcp/profile/` 에 persistent 저장
- **엔진**: Patchright (Playwright fork) + persistent browser profiles

### 제공 도구

| 도구 | 설명 |
|------|------|
| `search_people` | 키워드/회사/직함으로 사람 검색 |
| `get_person_profile` | LinkedIn URL로 프로필 상세 조회 |
| `get_company_profile` | 회사 프로필 조회 |
| `search_jobs` | 채용 공고 검색 |
| `get_job_details` | 채용 상세 조회 |
| `get_company_posts` | 회사 포스트 조회 |

### 리스크

- LinkedIn ToS 위반 가능 (자동화 차단)
- 과도한 사용 시 계정 제한
- DOM 변경 시 스크래퍼 파손 가능
