from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from bot.config.models import StrategiesConfig
from bot.domain.signals import (
    STRATEGY_VERSION,
    SignalDecision,
    SignalDirection,
    SignalType,
)
from bot.services.signals.admission import AdmissionRequest, StrategyAdmissionPolicy
from bot.services.signals.scoring import (
    MarketFeatures,
    ScoreResult,
    score_mean_reversion,
    score_mispricing,
    score_momentum_lag,
)


@dataclass(slots=True)
class SignalEvaluation:
    accepted: list[SignalDecision] = field(default_factory=list)
    rejected: list[SignalDecision] = field(default_factory=list)

    @property
    def evaluated_count(self) -> int:
        return len(self.accepted) + len(self.rejected)

    @property
    def rejection_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self.rejected:
            code = decision.rejection_code or "unknown"
            counts[code] = counts.get(code, 0) + 1
        return counts


@dataclass(slots=True)
class StrategyDiagnosticsSnapshot:
    enabled: bool
    legacy_bidirectional_enabled: bool
    enabled_strategies: list[str]
    disabled_strategies: list[str]
    min_confidence: float
    max_spread_bps: float
    min_liquidity_usd: float
    min_time_to_resolution_seconds: int
    max_position_fraction: float
    auto_execute_disabled: bool
    last_evaluated_count: int = 0
    last_accepted_count: int = 0
    last_rejected_count: int = 0
    last_rejection_counts: dict[str, int] = field(default_factory=dict)


class SignalEngine:
    """Runs enabled strategies over a market feature snapshot.

    Must not call execution adapters or mutate execution state. Callers may
    convert accepted SignalDecisions into proposal-ready artifacts via
    `to_proposal_artifact`, but proposal creation stays on the existing
    review-gated path.
    """

    def __init__(self, config: StrategiesConfig) -> None:
        self.config = config
        self.admission = StrategyAdmissionPolicy(config)
        self._last_evaluation: SignalEvaluation | None = None

    def evaluate(
        self,
        features: MarketFeatures,
        *,
        auto_execute_requested: bool = False,
    ) -> SignalEvaluation:
        evaluation = SignalEvaluation()
        if not self.config.enabled:
            self._last_evaluation = evaluation
            return evaluation

        scorers = [
            (SignalType.MOMENTUM_LAG, self.config.momentum_lag_enabled, score_momentum_lag),
            (SignalType.MEAN_REVERSION, self.config.mean_reversion_enabled, score_mean_reversion),
            (SignalType.MISPRICING, self.config.mispricing_enabled, score_mispricing),
        ]

        for signal_type, enabled, scorer in scorers:
            if not enabled:
                continue
            result: ScoreResult = scorer(features)
            if result.signal_type != signal_type:  # defensive, scorer contract.
                continue
            signal = result.to_signal(features.market_id, features.market_slug)
            decision = self.admission.evaluate(
                AdmissionRequest(
                    signal=signal,
                    features=features,
                    auto_execute_requested=auto_execute_requested,
                )
            )
            if decision.accepted:
                evaluation.accepted.append(decision)
            else:
                evaluation.rejected.append(decision)

        self._last_evaluation = evaluation
        return evaluation

    def diagnostics(self) -> StrategyDiagnosticsSnapshot:
        enabled_strategies: list[str] = []
        disabled_strategies: list[str] = []
        for name, flag in (
            (SignalType.MOMENTUM_LAG.value, self.config.momentum_lag_enabled),
            (SignalType.MEAN_REVERSION.value, self.config.mean_reversion_enabled),
            (SignalType.MISPRICING.value, self.config.mispricing_enabled),
            (SignalType.LEGACY_BIDIRECTIONAL.value, self.config.legacy_bidirectional_enabled),
        ):
            (enabled_strategies if flag else disabled_strategies).append(name)

        last = self._last_evaluation or SignalEvaluation()
        return StrategyDiagnosticsSnapshot(
            enabled=self.config.enabled,
            legacy_bidirectional_enabled=self.config.legacy_bidirectional_enabled,
            enabled_strategies=enabled_strategies,
            disabled_strategies=disabled_strategies,
            min_confidence=self.config.min_confidence,
            max_spread_bps=self.config.max_spread_bps,
            min_liquidity_usd=self.config.min_liquidity_usd,
            min_time_to_resolution_seconds=self.config.min_time_to_resolution_seconds,
            max_position_fraction=self.config.max_position_fraction,
            auto_execute_disabled=self.config.auto_execute_min_confidence is None,
            last_evaluated_count=last.evaluated_count,
            last_accepted_count=len(last.accepted),
            last_rejected_count=len(last.rejected),
            last_rejection_counts=last.rejection_counts,
        )


def to_proposal_artifact(decision: SignalDecision, *, now: datetime) -> dict[str, object]:
    """Convert an accepted SignalDecision into a proposal-ready artifact dict.

    This is intentionally a dict rather than a full TradeProposal: the
    proposal lifecycle still owns creation, policy evaluation, and persistence.
    The artifact carries the strategy-layer context so the existing proposal
    engine can later attach it to a proposal without any execution side-effect.
    """
    if not decision.accepted:
        raise ValueError("Cannot build proposal artifact from a rejected decision")
    signal = decision.signal
    side = _side_for(signal.direction)
    return {
        "strategy_version": STRATEGY_VERSION,
        "signal_type": signal.signal_type.value,
        "market_id": signal.market_id,
        "market_slug": signal.market_slug,
        "side": side,
        "confidence": decision.confidence,
        "proposed_size_fraction": decision.proposed_size_fraction,
        "features": dict(signal.features),
        "admission_reason": decision.reason,
        "risk_notes": _risk_notes(signal.signal_type),
        "created_at": now.isoformat(),
    }


def _side_for(direction: SignalDirection) -> str:
    if direction == SignalDirection.YES:
        return "yes"
    if direction == SignalDirection.NO:
        return "no"
    return "skip"


def _risk_notes(signal_type: SignalType) -> list[str]:
    if signal_type == SignalType.MOMENTUM_LAG:
        return [
            "BTC move may retrace before PM catches up.",
            "Confirm liquidity and spread before approval.",
        ]
    if signal_type == SignalType.MEAN_REVERSION:
        return [
            "News-driven moves can persist; verify no trigger before approving.",
            "Overextension may continue against a reversion thesis.",
        ]
    if signal_type == SignalType.MISPRICING:
        return ["Cross-market scanner is a placeholder; do not trade."]
    return ["Legacy strategy; do not trade."]
