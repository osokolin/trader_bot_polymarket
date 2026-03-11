from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot.domain.enums import PolicyRejectionReason


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reasons: list[PolicyRejectionReason] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ApprovalDecision:
    proposal_id: str
    approved: bool
    actor: str
    note: str | None = None

