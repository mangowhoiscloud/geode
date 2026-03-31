"""Tests for auto-learn hook (core/hooks/auto_learn.py)."""

from __future__ import annotations

from collections import Counter
from unittest.mock import MagicMock, patch

from core.hooks.auto_learn import (
    _MAX_PER_SESSION,
    _TOOL_USAGE_THRESHOLD,
    detect_patterns,
    make_auto_learn_handler,
)
from core.hooks.system import HookEvent

# ── detect_patterns tests ────────────────────────────────────────────────


class TestDetectSelfIntro:
    def test_english_i_am(self):
        r = detect_patterns("I am a game designer at Nexon", [], Counter())
        assert len(r) == 1
        assert r[0][1] == "preference"
        assert "self-intro" in r[0][0].lower()

    def test_english_im(self):
        r = detect_patterns("I'm a backend developer focused on Go", [], Counter())
        assert len(r) == 1
        assert "self-intro" in r[0][0].lower()

    def test_korean_naneun(self):
        r = detect_patterns("나는 데이터 사이언티스트야, ML 쪽 전문이야", [], Counter())
        assert len(r) == 1
        assert r[0][1] == "preference"

    def test_korean_jeoneun(self):
        r = detect_patterns("저는 프론트엔드 개발자입니다", [], Counter())
        assert len(r) == 1


class TestDetectExplicitPref:
    def test_i_prefer(self):
        r = detect_patterns("I prefer concise answers without fluff", [], Counter())
        assert len(r) == 1
        assert "preference" in r[0][0].lower()

    def test_dont_use(self):
        r = detect_patterns("don't use emojis in your responses please", [], Counter())
        assert len(r) == 1

    def test_from_now_on(self):
        r = detect_patterns("from now on always answer in bullet points", [], Counter())
        assert len(r) == 1

    def test_korean_apuro(self):
        r = detect_patterns("앞으로 코드 리뷰할 때 타입 체크도 같이 해줘", [], Counter())
        assert len(r) == 1


class TestDetectLanguagePref:
    def test_korean_ro(self):
        r = detect_patterns("한국어로 답변해줘 앞으로는", [], Counter())
        assert len(r) == 1
        assert "language" in r[0][0].lower()

    def test_english_respond_in(self):
        r = detect_patterns("please respond in english from now on", [], Counter())
        assert len(r) == 1
        assert "language" in r[0][0].lower()

    def test_answer_in_japanese(self):
        r = detect_patterns("can you answer in japanese for this session", [], Counter())
        assert len(r) == 1


class TestDetectDomainInterest:
    def test_interested_in(self):
        r = detect_patterns("I'm interested in dark fantasy game IPs", [], Counter())
        # self-intro ("I'm") wins over domain interest (first-match)
        assert len(r) == 1
        assert "self-intro" in r[0][0].lower()

    def test_working_on(self):
        r = detect_patterns("currently working on a recommendation engine for Steam", [], Counter())
        assert len(r) == 1
        assert r[0][1] == "domain"

    def test_researching(self):
        r = detect_patterns("we are researching autonomous agent architectures", [], Counter())
        assert len(r) == 1
        assert r[0][1] == "domain"


class TestDetectToolUsage:
    def test_threshold_emits_once(self):
        counter: Counter[str] = Counter()
        # Below threshold — no emission
        for _ in range(_TOOL_USAGE_THRESHOLD - 1):
            r = detect_patterns("short", ["web_fetch"], counter)
            tool_hits = [p for p in r if p[1] == "tool_usage"]
            assert tool_hits == []

        # At threshold — emits
        r = detect_patterns("short", ["web_fetch"], counter)
        tool_hits = [p for p in r if p[1] == "tool_usage"]
        assert len(tool_hits) == 1
        assert "web_fetch" in tool_hits[0][0]

        # Above threshold — no re-emission
        r = detect_patterns("short", ["web_fetch"], counter)
        tool_hits = [p for p in r if p[1] == "tool_usage"]
        assert tool_hits == []


class TestNoiseControl:
    def test_short_input_ignored(self):
        r = detect_patterns("hi", [], Counter())
        assert r == []

    def test_slash_command_ignored(self):
        r = detect_patterns("/help I am a developer", [], Counter())
        assert r == []

    def test_no_match_returns_empty(self):
        r = detect_patterns("what is the weather today in Seoul?", [], Counter())
        assert r == []

    def test_first_match_wins(self):
        # Contains both self-intro and domain interest, self-intro wins
        r = detect_patterns(
            "I'm focused on researching game IP potential",
            [],
            Counter(),
        )
        assert len(r) == 1
        assert "self-intro" in r[0][0].lower()

    def test_truncation_at_120(self):
        long_input = "I am a " + "x" * 200
        r = detect_patterns(long_input, [], Counter())
        assert len(r) == 1
        assert len(r[0][0]) <= len("User self-intro: ") + 120


# ── Hook handler tests ──────────────────────────────────────────────────


class TestAutoLearnHandler:
    def _make_mock_profile(self) -> MagicMock:
        profile = MagicMock()
        profile.add_learned_pattern.return_value = True
        return profile

    def test_saves_pattern_on_match(self):
        _, handler = make_auto_learn_handler()
        mock_profile = self._make_mock_profile()

        with patch("core.tools.profile_tools.get_user_profile", return_value=mock_profile):
            handler(
                HookEvent.TURN_COMPLETE,
                {"user_input": "I am a game designer at Nexon", "tool_calls": []},
            )

        mock_profile.add_learned_pattern.assert_called_once()
        args = mock_profile.add_learned_pattern.call_args
        assert "self-intro" in args[0][0].lower()
        assert args[0][1] == "preference"

    def test_no_profile_is_noop(self):
        _, handler = make_auto_learn_handler()

        with patch("core.tools.profile_tools.get_user_profile", return_value=None):
            # Should not raise
            handler(
                HookEvent.TURN_COMPLETE,
                {"user_input": "I am a game designer at Nexon", "tool_calls": []},
            )

    def test_cooldown_prevents_rapid_fire(self):
        _, handler = make_auto_learn_handler()
        mock_profile = self._make_mock_profile()

        with patch("core.tools.profile_tools.get_user_profile", return_value=mock_profile):
            handler(
                HookEvent.TURN_COMPLETE,
                {"user_input": "I am a game designer at Nexon", "tool_calls": []},
            )
            # Second call within cooldown — should be suppressed
            handler(
                HookEvent.TURN_COMPLETE,
                {"user_input": "I prefer concise answers always", "tool_calls": []},
            )

        assert mock_profile.add_learned_pattern.call_count == 1

    def test_session_cap(self):
        _, handler = make_auto_learn_handler()
        mock_profile = self._make_mock_profile()

        with (
            patch("core.tools.profile_tools.get_user_profile", return_value=mock_profile),
            patch("core.hooks.auto_learn._COOLDOWN_S", 0),  # disable cooldown for this test
        ):
            for i in range(_MAX_PER_SESSION + 5):
                handler(
                    HookEvent.TURN_COMPLETE,
                    {"user_input": f"I am developer number {i} at company", "tool_calls": []},
                )

        assert mock_profile.add_learned_pattern.call_count == _MAX_PER_SESSION

    def test_dedup_not_counted(self):
        """Dedup (add_learned_pattern returns False) doesn't increment session count."""
        _, handler = make_auto_learn_handler()
        mock_profile = self._make_mock_profile()
        mock_profile.add_learned_pattern.return_value = False  # dedup

        with (
            patch("core.tools.profile_tools.get_user_profile", return_value=mock_profile),
            patch("core.hooks.auto_learn._COOLDOWN_S", 0),
        ):
            handler(
                HookEvent.TURN_COMPLETE,
                {"user_input": "I am a game designer at Nexon", "tool_calls": []},
            )
            handler(
                HookEvent.TURN_COMPLETE,
                {"user_input": "I prefer dark fantasy game IPs", "tool_calls": []},
            )

        # Both attempted, neither counted toward session cap
        assert mock_profile.add_learned_pattern.call_count == 2

    def test_exception_in_profile_is_swallowed(self):
        _, handler = make_auto_learn_handler()
        mock_profile = self._make_mock_profile()
        mock_profile.add_learned_pattern.side_effect = OSError("disk full")

        with patch("core.tools.profile_tools.get_user_profile", return_value=mock_profile):
            # Should not raise
            handler(
                HookEvent.TURN_COMPLETE,
                {"user_input": "I am a game designer at Nexon", "tool_calls": []},
            )


class TestHookRegistration:
    def test_auto_learn_registered_in_build_hooks(self):
        from unittest.mock import patch

        with (
            patch("core.runtime_wiring.bootstrap.RunLog"),
            patch("core.runtime_wiring.bootstrap.StuckDetector"),
        ):
            from core.runtime_wiring.bootstrap import build_hooks

            hooks, _, _, _ = build_hooks(
                session_key="test",
                run_id="test-run",
                log_dir=None,
                stuck_timeout_s=60,
            )

        all_hooks = hooks.list_hooks()
        assert "turn_auto_learn" in all_hooks.get("turn_complete", [])
