from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bot.config.models import StrategiesConfig
from bot.domain.signals import SignalDecision, SignalDirection, SignalType, StrategySignal
from bot.services.signals.scoring import MarketFeatures


class AdmissionRejection(str, Enum):
    STRATEGIES_DISABLED = "strategies_disabled"
    LEGACY_BIDIRECTIONAL_DISABLED = "legacy_bidirectional_disabled"
    STRATEGY_TYPE_DISABLED = "strategy_type_disabled"
    SKIP_DIRECTION = "skip_direction"
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    SPREAD_TOO_WIDE = "spread_too_wide"
    LIQUIDITY_TOO_LOW = "liquidity_too_low"
    TIME_TO_RESOLUTION_TOO_SHORT = "time_to_resolution_too_short"
    AUTO_EXECUTE_REQUESTED = "auto_execute_requested"


@dataclass(slots=True)
class AdmissionRequest:
    signal: StrategySignal
    features: MarketFeatures
    auto_execute_requested: bool = False


def _strategy_type_enabled(signal_type: SignalType, config: StrategiesConfig) -> bool:
    if signal_type == SignalType.MOMENTUM_LAG:
        return config.momentum_lag_enabled
    if signal_type == SignalType.MEAN_REVERSION:
        return config.mean_reversion_enabled
    if signal_type == SignalType.MISPRICING:
        return config.mispricing_enabled
    if signal_type == SignalType.LEGACY_BIDIRECTIONAL:
        return config.legacy_bidirectional_enabled
    return False


class StrategyAdmissionPolicy:
    """Central admission gate for strategy signals.

    - Never raises for a normal rejection.
    - Rejects any signal tagged as bidirectional/hedged/dual_side/both_sides
      (or with signal_type == LEGACY_BIDIRECTIONAL) unless the legacy flag is on.
    - Returns a structured SignalDecision with an explicit rejection_code so
      callers can log/audit the outcome.
    """

    def __init__(self, config: StrategiesConfig) -> None:
        self.config = config

    def evaluate(self, request: AdmissionRequest) -> SignalDecision:
        signal = request.signal
        features = request.features
        size_fraction = 0.0

        if not self.config.enabled:
            return self._reject(signal, AdmissionRejection.STRATEGIES_DISABLED, size_fraction)

        if signal.has_legacy_tag() and not self.config.legacy_bidirectional_enabled:
            return self._reject(signal, AdmissionRejection.LEGACY_BIDIRECTIONAL_DISABLED, size_fraction)

        if not _strategy_type_enabled(signal.signal_type, self.config):
            return self._reject(signal, AdmissionRejection.STRATEGY_TYPE_DISABLED, size_fraction)

        if signal.direction == SignalDirection.SKIP:
            return self._reject(signal, AdmissionRejection.SKIP_DIRECTION, size_fraction)

        if request.auto_execute_requested or self.config.auto_execute_min_confidence is not None:
            return self._reject(signal, AdmissionRejection.AUTO_EXECUTE_REQUESTED, size_fraction)

        if features.seconds_to_resolution < self.config.min_time_to_resolution_seconds:
            return self._reject(signal, AdmissionRejection.TIME_TO_RESOLUTION_TOO_SHORT, size_fraction)

        if features.liquidity_usd < self.config.min_liquidity_usd:
            return self._reject(signal, AdmissionRejection.LIQUIDITY_TOO_LOW, size_fraction)

        if features.spread_bps > self.config.max_spread_bps:
            return self._reject(signal, AdmissionRejection.SPREAD_TOO_WIDE, size_fraction)

        if signal.confidence < self.config.min_confidence:
            return self._reject(signal, AdmissionRejection.CONFIDENCE_BELOW_THRESHOLD, size_fraction)

        size_fraction = self._size_fraction(signal.confidence)
        return SignalDecision(
            accepted=True,
            reason=f"admitted:{signal.signal_type.value}",
            signal=signal,
            confidence=signal.confidence,
            proposed_size_fraction=size_fraction,
            rejection_code=None,
        )

    def _size_fraction(self, confidence: float) -> float:
        cap = self.config.max_position_fraction
        min_conf = self.config.min_confidence
        if cap <= 0 or confidence <= min_conf:
            return 0.0
        # Linear scale between min_confidence and 1.0, capped by max_position_fraction.
        span = max(1.0 - min_conf, 1e-6)
        scale = (confidence - min_conf) / span
        if scale < 0.0:
            return 0.0
        if scale > 1.0:
            scale = 1.0
        return round(cap * scale, 6)

    def _reject(
        self,
        signal: StrategySignal,
        code: AdmissionRejection,
        size_fraction: float,
    ) -> SignalDecision:
        return SignalDecision(
            accepted=False,
            reason=f"rejected:{code.value}",
            signal=signal,
            confidence=signal.confidence,
            proposed_size_fraction=size_fraction,
            rejection_code=code.value,
        )
