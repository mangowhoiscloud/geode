"""Tests for GAP-5: IP Rights/License Risk Assessment."""

from __future__ import annotations

import pytest

from geode.verification.rights_risk import (
    LicenseInfo,
    RightsRiskResult,
    RightsStatus,
    check_rights_risk,
)


class TestRightsStatus:
    def test_enum_values(self):
        assert RightsStatus.CLEAR.value == "clear"
        assert RightsStatus.NEGOTIABLE.value == "negotiable"
        assert RightsStatus.RESTRICTED.value == "restricted"
        assert RightsStatus.EXPIRED.value == "expired"
        assert RightsStatus.UNKNOWN.value == "unknown"

    def test_all_statuses_count(self):
        assert len(RightsStatus) == 5


class TestLicenseInfo:
    def test_basic_creation(self):
        info = LicenseInfo(holder="Test Corp", status=RightsStatus.CLEAR)
        assert info.holder == "Test Corp"
        assert info.status == RightsStatus.CLEAR
        assert info.expiry_year is None
        assert info.territories == []
        assert info.exclusivity is False

    def test_full_creation(self):
        info = LicenseInfo(
            holder="Bandai Namco",
            status=RightsStatus.NEGOTIABLE,
            expiry_year=2030,
            territories=["JP", "NA", "EU"],
            exclusivity=True,
        )
        assert info.expiry_year == 2030
        assert len(info.territories) == 3
        assert info.exclusivity is True


class TestRightsRiskResult:
    def test_risk_score_bounds(self):
        result = RightsRiskResult(
            status=RightsStatus.CLEAR,
            risk_score=0,
            license_info=LicenseInfo(holder="X", status=RightsStatus.CLEAR),
        )
        assert result.risk_score == 0

    def test_risk_score_max(self):
        result = RightsRiskResult(
            status=RightsStatus.UNKNOWN,
            risk_score=100,
            license_info=LicenseInfo(holder="X", status=RightsStatus.UNKNOWN),
        )
        assert result.risk_score == 100

    def test_risk_score_out_of_range_raises(self):
        with pytest.raises(ValueError):
            RightsRiskResult(
                status=RightsStatus.CLEAR,
                risk_score=101,
                license_info=LicenseInfo(holder="X", status=RightsStatus.CLEAR),
            )


class TestCheckRightsRisk:
    def test_cowboy_bebop_negotiable(self):
        result = check_rights_risk("Cowboy Bebop")
        assert result.status == RightsStatus.NEGOTIABLE
        assert 30 <= result.risk_score <= 60
        assert "Sunrise" in result.license_info.holder or "Bandai" in result.license_info.holder
        assert len(result.concerns) >= 2
        assert "NEGOTIABLE" in result.recommendation

    def test_berserk_restricted(self):
        result = check_rights_risk("Berserk")
        assert result.status == RightsStatus.RESTRICTED
        assert result.risk_score > 60
        assert "Hakusensha" in result.license_info.holder
        assert any("estate" in c.lower() or "miura" in c.lower() for c in result.concerns)
        assert "RESTRICTED" in result.recommendation

    def test_ghost_in_shell_negotiable(self):
        result = check_rights_risk("Ghost in the Shell")
        assert result.status == RightsStatus.NEGOTIABLE
        assert 30 <= result.risk_score <= 60
        assert "Kodansha" in result.license_info.holder
        assert len(result.concerns) >= 2

    def test_case_insensitive_lookup(self):
        r1 = check_rights_risk("cowboy bebop")
        r2 = check_rights_risk("COWBOY BEBOP")
        r3 = check_rights_risk("  Cowboy Bebop  ")
        assert r1.status == r2.status == r3.status

    def test_unknown_ip_returns_unknown(self):
        result = check_rights_risk("Nonexistent IP XYZ")
        assert result.status == RightsStatus.UNKNOWN
        assert result.risk_score >= 70
        assert result.license_info.holder == "Unknown"
        assert "UNKNOWN" in result.recommendation

    def test_unknown_ip_concerns_mention_name(self):
        result = check_rights_risk("My Custom IP")
        assert any("My Custom IP" in c for c in result.concerns)

    def test_ip_info_parameter_accepted(self):
        # ip_info is accepted but not used in demo mode
        result = check_rights_risk("Berserk", ip_info={"extra": "data"})
        assert result.status == RightsStatus.RESTRICTED
