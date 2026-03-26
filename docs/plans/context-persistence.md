# context-persistence

## 문제
재설치/업그레이드/clone 시 유저 프로필이 휘발되는 것처럼 보임.

## 근인 분석
글로벌 프로필(`~/.geode/user_profile/`)은 재설치 시 유지됨. 하지만:

1. **프로젝트 프로필 미추적**: `.gitignore`가 `.geode/user_profile/` 차단 → clone 시 유실
2. **글로벌→프로젝트 자동 시딩 없음**: `geode init` 시 프로젝트 프로필 미생성
3. **프로필 로드 실패 무성 스킵**: `setup_user_profile()` → `except Exception: pass`
4. **settings.user_profile_dir 기본값 ""**: runtime.py에서 None으로 변환

## 수정 계획

### Fix 1: `geode init` 시 글로벌 프로필 → 프로젝트 시딩
- `~/.geode/user_profile/`이 있으면 `.geode/user_profile/`로 복사
- 이미 존재하면 skip (덮어쓰기 방지)

### Fix 2: bootstrap에서 프로필 로드 실패 시 경고 로그
- `except Exception: pass` → `except Exception: log.warning(...)`
- 무성 실패 제거

### Fix 3: .gitignore에 user_profile 화이트리스트 검토
- `.geode/user_profile/profile.md`는 추적 가치 있음 (팀 공유)
- `preferences.json`, `learned.md`는 개인 데이터 → 미추적 유지

### Fix 4: 프로필 존재 여부 상태 표시
- REPL 시작 시 `✓ User Profile loaded` 또는 `⚠ No user profile found`
- `/status`에 프로필 상태 포함

## 소크라틱 게이트
- Q1: 프로필 로드 로직 있지만 실패 시 무성 → 구현 부분적
- Q2: 유저가 "프로필이 안 보인다"고 피드백 → 실질 문제
- Q3: 프로필 로드 성공률 로그로 측정
- Q4: warning 로그 + init 시 시딩 (최소 변경)
- Q5: Claude Code는 `~/.claude/` 영속, Codex는 `~/.codex/auth.json` 영속
