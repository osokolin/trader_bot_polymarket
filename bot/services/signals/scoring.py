from __future__ import annotations

from dataclasses import dataclass

from bot.domain.signals import SignalDirection, SignalType, StrategySignal


@dataclass(slots=True)
class MarketFeatures:
    market_id: str
    market_slug: str
    liquidity_usd: float
    spread_bps: float
    seconds_to_resolution: int
    current_probability: float
    # Momentum Lag inputs.
    btc_move_pct: float = 0.0
    polymarket_probability_move_pct: float = 0.0
    # Mean Reversion inputs.
    recent_probability_move_pct: float = 0.0
    has_news_trigger: bool = False


@dataclass(slots=True)
class ScoreResult:
    signal_type: SignalType
    direction: SignalDirection
    confidence: float
    reason: str
    features: dict[str, float]

    def to_signal(self, market_id: str, market_slug: str) -> StrategySignal:
        return StrategySignal(
            market_id=market_id,
            market_slug=market_slug,
            signal_type=self.signal_type,
            direction=self.direction,
            confidence=self.confidence,
            reason=self.reason,
            features=dict(self.features),
        )


def _clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


def score_momentum_lag(features: MarketFeatures) -> ScoreResult:
    """Momentum Lag Exploit scoring.

    Idea: a strong BTC move should drag an under-reacted PM probability along.
    Stronger BTC move, larger lag, more liquidity, tighter spread, and more
    time-to-resolution all raise confidence.
    """
    btc_move = features.btc_move_pct
    pm_move = features.polymarket_probability_move_pct
    lag = abs(btc_move) - abs(pm_move)
    if abs(btc_move) < 0.003 or lag <= 0:
        return ScoreResult(
            signal_type=SignalType.MOMENTUM_LAG,
            direction=SignalDirection.SKIP,
            confidence=0.0,
            reason="no_directional_lag",
            features=_momentum_feature_dump(features, lag),
        )

    direction = SignalDirection.YES if btc_move > 0 else SignalDirection.NO

    # Normalize components into 0..1 contributions.
    btc_strength = _clamp01(abs(btc_move) / 0.02)  # 2% BTC move saturates.
    lag_strength = _clamp01(lag / 0.02)
    liquidity_strength = _clamp01(features.liquidity_usd / 50_000.0)
    spread_penalty = _clamp01(features.spread_bps / 300.0)
    resolution_penalty = 0.0 if features.seconds_to_resolution >= 1800 else 0.5

    raw = (
        0.40 * btc_strength
        + 0.30 * lag_strength
        + 0.20 * liquidity_strength
        - 0.25 * spread_penalty
        - resolution_penalty * 0.20
    )
    confidence = _clamp01(0.55 + raw * 0.50)

    return ScoreResult(
        signal_type=SignalType.MOMENTUM_LAG,
        direction=direction,
        confidence=confidence,
        reason=f"btc_move={btc_move:+.4f} pm_move={pm_move:+.4f} lag={lag:+.4f}",
        features=_momentum_feature_dump(features, lag),
    )


def _momentum_feature_dump(features: MarketFeatures, lag: float) -> dict[str, float]:
    return {
        "btc_move_pct": features.btc_move_pct,
        "polymarket_probability_move_pct": features.polymarket_probability_move_pct,
        "lag_pct": lag,
        "liquidity_usd": features.liquidity_usd,
        "spread_bps": features.spread_bps,
        "seconds_to_resolution": float(features.seconds_to_resolution),
    }


def score_mean_reversion(features: MarketFeatures) -> ScoreResult:
    """Mean Reversion scoring.

    Idea: an overextended probability with no news trigger is a candidate for
    reversion. High spread is penalised; very strong recent volume-confirmed
    moves dampen confidence because they suggest real information.
    """
    prob = features.current_probability
    overextension = max(prob - 0.80, 0.20 - prob)
    if overextension <= 0:
        return ScoreResult(
            signal_type=SignalType.MEAN_REVERSION,
            direction=SignalDirection.SKIP,
            confidence=0.0,
            reason="not_overextended",
            features=_reversion_feature_dump(features, overextension),
        )
    if features.has_news_trigger:
        return ScoreResult(
            signal_type=SignalType.MEAN_REVERSION,
            direction=SignalDirection.SKIP,
            confidence=0.0,
            reason="news_trigger_present",
            features=_reversion_feature_dump(features, overextension),
        )

    direction = SignalDirection.NO if prob >= 0.80 else SignalDirection.YES

    overextension_strength = _clamp01(overextension / 0.15)
    liquidity_strength = _clamp01(features.liquidity_usd / 50_000.0)
    spread_penalty = _clamp01(features.spread_bps / 300.0)
    # Strong volume-confirmed move = less confident reversion.
    volume_confirmation = _clamp01(abs(features.recent_probability_move_pct) / 0.10)

    raw = (
        0.45 * overextension_strength
        + 0.20 * liquidity_strength
        - 0.25 * spread_penalty
        - 0.30 * volume_confirmation
    )
    confidence = _clamp01(0.55 + raw * 0.50)

    return ScoreResult(
        signal_type=SignalType.MEAN_REVERSION,
        direction=direction,
        confidence=confidence,
        reason=f"prob={prob:.3f} overext={overextension:+.3f}",
        features=_reversion_feature_dump(features, overextension),
    )


def _reversion_feature_dump(features: MarketFeatures, overextension: float) -> dict[str, float]:
    return {
        "current_probability": features.current_probability,
        "overextension": overextension,
        "recent_probability_move_pct": features.recent_probability_move_pct,
        "liquidity_usd": features.liquidity_usd,
        "spread_bps": features.spread_bps,
        "has_news_trigger": 1.0 if features.has_news_trigger else 0.0,
    }


def score_mispricing(features: MarketFeatures) -> ScoreResult:
    """Cross-market mispricing placeholder.

    Intentionally never emits an actionable signal; the real scanner needs
    cross-market data wiring that is out of scope for Signal Engine v1.
    """
    return ScoreResult(
        signal_type=SignalType.MISPRICING,
        direction=SignalDirection.SKIP,
        confidence=0.0,
        reason="mispricing_scanner_placeholder",
        features={
            "liquidity_usd": features.liquidity_usd,
            "spread_bps": features.spread_bps,
            "current_probability": features.current_probability,
        },
    )
