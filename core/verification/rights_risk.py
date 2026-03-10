"""GAP-5: IP Rights/License Risk Assessment.

Evaluates licensing complexity, territorial restrictions, and
expiration risk for candidate IPs. In production, integrates
with legal/rights databases; demo uses hardcoded fixture data.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RightsStatus(StrEnum):
    """IP rights clearance status."""

    CLEAR = "clear"
    NEGOTIABLE = "negotiable"
    RESTRICTED = "restricted"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class LicenseInfo(BaseModel):
    """License details for an IP holder."""

    holder: str
    status: RightsStatus
    expiry_year: int | None = None
    territories: list[str] = Field(default_factory=list)
    exclusivity: bool = False


class RightsRiskResult(BaseModel):
    """Result of IP rights/license risk assessment."""

    status: RightsStatus
    risk_score: int = Field(ge=0, le=100)
    license_info: LicenseInfo
    concerns: list[str] = Field(default_factory=list)
    recommendation: str = ""


# ---------------------------------------------------------------------------
# Hardcoded fixture data for demo IPs
# ---------------------------------------------------------------------------

_FIXTURE_RIGHTS: dict[str, dict[str, Any]] = {
    "cowboy bebop": {
        "holder": "Sunrise / Bandai Namco",
        "status": RightsStatus.NEGOTIABLE,
        "expiry_year": None,
        "territories": ["global"],
        "exclusivity": False,
        "risk_score": 45,
        "concerns": [
            "Multiple rights holders (Sunrise animation, Bandai Namco games)",
            "Previous game license (2005) was JP-only — territory restrictions possible",
            "Netflix live-action adaptation complicates licensing landscape",
        ],
        "recommendation": (
            "NEGOTIABLE — Bandai Namco holds game rights but multi-party "
            "negotiation required. Recommend early engagement with Sunrise "
            "for animation asset licensing. Medium complexity."
        ),
    },
    "berserk": {
        "holder": "Hakusensha / Young Animal",
        "status": RightsStatus.RESTRICTED,
        "expiry_year": None,
        "territories": ["global"],
        "exclusivity": False,
        "risk_score": 72,
        "concerns": [
            "Original creator Kentaro Miura passed away (2021) — estate management",
            "Manga continuation status affects long-term IP viability",
            "Previous game (Koei Tecmo, 2016) received mixed reviews — brand risk",
            "Dark/mature content may limit platform distribution channels",
        ],
        "recommendation": (
            "RESTRICTED — Estate and publisher approval required. Unfinished "
            "manga status creates uncertainty for long-term IP investment. "
            "High complexity; recommend contingency clauses in any agreement."
        ),
    },
    "ghost in the shell": {
        "holder": "Kodansha / Production I.G",
        "status": RightsStatus.NEGOTIABLE,
        "expiry_year": None,
        "territories": ["global"],
        "exclusivity": False,
        "risk_score": 40,
        "concerns": [
            "Split rights between Kodansha (manga) and Production I.G (anime)",
            "Hollywood adaptation (Paramount) may hold residual game rights",
            "Multiple franchise iterations complicate which version to license",
        ],
        "recommendation": (
            "NEGOTIABLE — Kodansha is open to game licensing; Production I.G "
            "holds anime adaptation rights. Recommend targeting manga-based "
            "license to avoid Hollywood entanglements. Medium complexity."
        ),
    },
}


def check_rights_risk(ip_name: str, ip_info: dict[str, Any] | None = None) -> RightsRiskResult:
    """Assess IP rights and licensing risk.

    Args:
        ip_name: Name of the IP to assess.
        ip_info: Optional IP info dict (used for enrichment in production).

    Returns:
        RightsRiskResult with status, risk score, and recommendations.
    """
    key = ip_name.lower().strip()
    fixture = _FIXTURE_RIGHTS.get(key)

    if fixture is None:
        # Unknown IP — return UNKNOWN status with high risk
        return RightsRiskResult(
            status=RightsStatus.UNKNOWN,
            risk_score=80,
            license_info=LicenseInfo(
                holder="Unknown",
                status=RightsStatus.UNKNOWN,
                territories=[],
            ),
            concerns=[
                f"No rights data available for '{ip_name}'",
                "Rights holder identification required before proceeding",
                "Recommend legal team research before pipeline advancement",
            ],
            recommendation=(
                f"UNKNOWN — No licensing data for '{ip_name}'. "
                "Full rights clearance research required before evaluation."
            ),
        )

    license_info = LicenseInfo(
        holder=fixture["holder"],
        status=fixture["status"],
        expiry_year=fixture.get("expiry_year"),
        territories=fixture.get("territories", []),
        exclusivity=fixture.get("exclusivity", False),
    )

    return RightsRiskResult(
        status=fixture["status"],
        risk_score=fixture["risk_score"],
        license_info=license_info,
        concerns=fixture["concerns"],
        recommendation=fixture["recommendation"],
    )
