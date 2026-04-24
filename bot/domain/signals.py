from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SignalType(str, Enum):
    MOMENTUM_LAG = "momentum_lag"
    MEAN_REVERSION = "mean_reversion"
    MISPRICING = "mispricing"
    LEGACY_BIDIRECTIONAL = "legacy_bidirectional"


class SignalDirection(str, Enum):
    YES = "yes"
    NO = "no"
    SKIP = "skip"


# Tags used to flag legacy/unsafe scenarios. Any signal carrying one of these
# must be rejected unless strategies.legacy_bidirectional_enabled is true.
LEGACY_BIDIRECTIONAL_TAGS: frozenset[str] = frozenset(
    {"bidirectional", "hedge", "hedged", "dual_side", "both_sides", "long_short", "yes_no"}
)


@dataclass(slots=True)
class StrategySignal:
    market_id: str
    market_slug: str
    signal_type: SignalType
    direction: SignalDirection
    confidence: float
    reason: str
    features: dict[str, float] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None

    def has_legacy_tag(self) -> bool:
        if self.signal_type == SignalType.LEGACY_BIDIRECTIONAL:
            return True
        return any(tag in LEGACY_BIDIRECTIONAL_TAGS for tag in self.tags)


@dataclass(slots=True)
class SignalDecision:
    accepted: bool
    reason: str
    signal: StrategySignal
    confidence: float
    proposed_size_fraction: float
    rejection_code: str | None = None


STRATEGY_VERSION = "signal_engine_v1"
