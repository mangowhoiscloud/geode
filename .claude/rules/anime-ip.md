---
name: anime-ip-rules
paths:
  - "**/*anime*"
  - "*cowboy*"
  - "*ghost*"
---

# 애니메이션 IP 분석 규칙

## 데이터 소스 우선순위
1. YouTube (트레일러, 리뷰 영상)
2. Reddit (r/anime, r/gaming)

## 특수 고려사항
- 원작 시즌 방영 중이면 Growth Velocity(J) 가중치 상향
- 원작 완결 후 2년 이상이면 Expansion Potential(F) 감점
