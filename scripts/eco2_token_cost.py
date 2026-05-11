"""Eco² Performance category 의 13 posting 의 token 소모 + model grounding 의 cost 추정.

13 posting 의 본문 의 WebFetch 의 결과 (2026-05-12 retrieval) 의 hard-code.
본 fuzzy model attribution (대부분 "OpenAI Tier 4", "LLM x2" 의 명시) 의
conservative + aggressive range 의 계산.

Source: https://rooftopsnow.tistory.com/category/이코에코(Eco²)%20Context/Performance
"""

# OpenAI Tier 4 (TPM 4M) 의 본 시기 의 default model 의 가정:
# - 2025-Q4 ~ 2026-Q1 default: gpt-4o ($2.50/$10) 또는 gpt-5.4 ($2.50/$15)
# - 본 사용자 의 blog dates: 2026-01-27 의 명시 → gpt-4o (Tier 4 의 popular default)
# 보수 / 적극 model assumption 두 path 의 계산.

PRICING = {
    "gpt-4o":          {"in": 2.50, "out": 10.00},   # USD per 1M tokens
    "gpt-5.4":         {"in": 2.50, "out": 15.00},
    "gpt-5.5":         {"in": 5.00, "out": 30.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
}
USD_TO_KRW = 1400

# 13 posting 의 token estimate (input + output 합산).
# 본 사용자 의 blog 의 명시 + 본 TPM 의 추정 의 conservative.
# /17 의 "104M tokens (Tier 3)" 의 명시 가 핵심 grounding.
POSTINGS = [
    # (url_suffix, title, total_tokens, model_hint, notes)
    ("/259", "VU 1000 [minR 2/5]",  8_000_000, "openai_tier4", "TPM ~50% × ~3min"),
    ("/258", "VU 900",              7_660_000, "openai_tier4", "명시: 7.66M / 3min"),
    ("/257", "VU 800",              7_500_000, "openai_tier4", "~57% TPM 4M × ~3min"),
    ("/256", "VU 700",              6_600_000, "openai_tier4", "~55% TPM 4M × ~3min"),
    ("/255", "VU 1000 (Tier 4)",   12_000_000, "openai_tier4", "TPM peak 의 4M × ~3min"),
    ("/254", "VU 1000 (Tier 3)",    6_000_000, "openai_tier3", "TPM 2M ceiling × ~3min"),
    ("/253", "VU 600",              6_000_000, "openai_tier4", "TPM ~40% × ~3min"),
    ("/252", "VU 500",              5_000_000, "openai_tier4", "TPM ~30% × ~3min"),
    ("/111", "VU 600 (이전 round)",  3_500_000, "openai_tier3", "33% 의 fail, 부분 ~"),
    ("/108", "Streams & Scaling #11", 3_000_000, "openai_tier3", "VU 200-300, 부하"),
    ("/107", "Streams & Scaling #10", 2_500_000, "openai_tier3", "VU 50-300, 부하"),
    ("/78",  "Gevent+Celery 50 VU",  1_000_000, "openai_tier3", "VU 50, 1 batch"),
    ("/17",  "Scan API 성능 측정",  104_000_000, "openai_tier3", "명시: 104M tokens 의 단일 round"),
]

def model_cost(tokens, in_per_m, out_per_m, in_ratio=0.6):
    """본 input/output split 의 default 60/40 의 가정.

    Scan API 의 vision + answer 의 본 ratio — input (image + prompt) 의 큰 + output (answer) 의 작은.
    본 60/40 의 보수 추정.
    """
    in_tokens = tokens * in_ratio
    out_tokens = tokens * (1 - in_ratio)
    return (in_tokens * in_per_m + out_tokens * out_per_m) / 1_000_000

# 본 두 path 의 계산:
# 보수 (gpt-4o): 본 시기 의 default
# 적극 (gpt-5.4): 본 후 release 의 default

print("=" * 80)
print(f"{'Post':<40} {'Tokens (M)':>12} {'gpt-4o ($)':>12} {'gpt-5.4 ($)':>12}")
print("=" * 80)

total_tokens = 0
total_4o = 0
total_54 = 0
for url, title, tokens, hint, notes in POSTINGS:
    cost_4o = model_cost(tokens, PRICING["gpt-4o"]["in"], PRICING["gpt-4o"]["out"])
    cost_54 = model_cost(tokens, PRICING["gpt-5.4"]["in"], PRICING["gpt-5.4"]["out"])
    total_tokens += tokens
    total_4o += cost_4o
    total_54 += cost_54
    name = f"{url} {title[:30]}"
    print(f"{name:<40} {tokens/1e6:>12.2f} {cost_4o:>12.2f} {cost_54:>12.2f}")

print("=" * 80)
print(f"{'TOTAL':<40} {total_tokens/1e6:>12.2f} {total_4o:>12.2f} {total_54:>12.2f}")
print()
print(f"환산 (1 USD = {USD_TO_KRW} KRW):")
print(f"  gpt-4o 의 cost: ${total_4o:.2f} = {total_4o * USD_TO_KRW:,.0f} KRW")
print(f"  gpt-5.4 의 cost: ${total_54:.2f} = {total_54 * USD_TO_KRW:,.0f} KRW")
print()
print(f"보수 ({USD_TO_KRW} KRW/USD, gpt-4o, 60/40 in/out split): {total_4o * USD_TO_KRW / 1_0000:.0f} 만원")
print(f"적극 ({USD_TO_KRW} KRW/USD, gpt-5.4, 60/40 in/out split): {total_54 * USD_TO_KRW / 1_0000:.0f} 만원")
