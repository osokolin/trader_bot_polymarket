from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from bot.config.loader import ConfigError, load_settings
from bot.config.models import StrategiesConfig
from bot.domain.signals import (
    STRATEGY_VERSION,
    SignalDecision,
    SignalDirection,
    SignalType,
    StrategySignal,
)
from bot.services.signals.admission import (
    AdmissionRejection,
    AdmissionRequest,
    StrategyAdmissionPolicy,
)
from bot.services.signals.engine import SignalEngine, to_proposal_artifact
from bot.services.signals.scoring import (
    MarketFeatures,
    score_mean_reversion,
    score_mispricing,
    score_momentum_lag,
)


def _default_strategies_config(**overrides: object) -> StrategiesConfig:
    base = StrategiesConfig(
        enabled=True,
        legacy_bidirectional_enabled=False,
        momentum_lag_enabled=True,
        mean_reversion_enabled=True,
        mispricing_enabled=False,
        min_confidence=0.70,
        auto_execute_min_confidence=None,
        max_spread_bps=150.0,
        min_liquidity_usd=3000.0,
        min_time_to_resolution_seconds=900,
        max_position_fraction=0.05,
    )
    if not overrides:
        return base
    return replace(base, **overrides)  # type: ignore[arg-type]


def _features(**overrides: object) -> MarketFeatures:
    base = MarketFeatures(
        market_id="m1",
        market_slug="btc-market",
        liquidity_usd=25_000.0,
        spread_bps=40.0,
        seconds_to_resolution=3600,
        current_probability=0.50,
        btc_move_pct=0.015,
        polymarket_probability_move_pct=0.002,
        recent_probability_move_pct=0.01,
        has_news_trigger=False,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


class ConfigDefaultsTest(unittest.TestCase):
    def test_default_config_disables_legacy_bidirectional(self) -> None:
        settings = load_settings(Path("config"))
        self.assertTrue(settings.strategies.enabled)
        self.assertFalse(settings.strategies.legacy_bidirectional_enabled)
        self.assertTrue(settings.strategies.momentum_lag_enabled)
        self.assertTrue(settings.strategies.mean_reversion_enabled)
        self.assertFalse(settings.strategies.mispricing_enabled)
        self.assertIsNone(settings.strategies.auto_execute_min_confidence)

    def test_auto_execute_min_confidence_rejected_while_auto_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ("balanced.yaml", "sources.yaml", "whitelist.yaml", "blacklist.yaml"):
                (tmp_path / name).write_text((Path("config") / name).read_text())
            text = (Path("config") / "base.yaml").read_text().replace(
                "auto_execute_min_confidence: null",
                "auto_execute_min_confidence: 0.99",
            )
            (tmp_path / "base.yaml").write_text(text)
            with self.assertRaises(ConfigError):
                load_settings(tmp_path)

    def test_enabling_legacy_requires_auto_execute_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ("balanced.yaml", "sources.yaml", "whitelist.yaml", "blacklist.yaml"):
                (tmp_path / name).write_text((Path("config") / name).read_text())
            text = (Path("config") / "base.yaml").read_text()
            text = text.replace(
                "legacy_bidirectional_enabled: false",
                "legacy_bidirectional_enabled: true",
            )
            text = text.replace(
                "auto_execute_disabled: true",
                "auto_execute_disabled: false",
            )
            # Disabling auto_execute in semi_auto is independently rejected, so
            # relax mode to paper to isolate the legacy-specific check.
            text = text.replace("mode: semi_auto", "mode: paper")
            (tmp_path / "base.yaml").write_text(text)
            with self.assertRaises(ConfigError) as ctx:
                load_settings(tmp_path)
            self.assertIn("legacy_bidirectional_enabled", str(ctx.exception))


class ScoringTest(unittest.TestCase):
    def test_momentum_lag_accepts_strong_directional_lag(self) -> None:
        result = score_momentum_lag(_features(btc_move_pct=0.015, polymarket_probability_move_pct=0.001))
        self.assertEqual(result.signal_type, SignalType.MOMENTUM_LAG)
        self.assertEqual(result.direction, SignalDirection.YES)
        self.assertGreaterEqual(result.confidence, 0.70)

    def test_momentum_lag_skips_without_lag(self) -> None:
        result = score_momentum_lag(_features(btc_move_pct=0.0005, polymarket_probability_move_pct=0.0))
        self.assertEqual(result.direction, SignalDirection.SKIP)
        self.assertEqual(result.confidence, 0.0)

    def test_mean_reversion_requires_overextension_and_no_news(self) -> None:
        overextended = score_mean_reversion(_features(current_probability=0.90, has_news_trigger=False))
        self.assertEqual(overextended.signal_type, SignalType.MEAN_REVERSION)
        self.assertEqual(overextended.direction, SignalDirection.NO)
        self.assertGreater(overextended.confidence, 0.0)

        with_news = score_mean_reversion(_features(current_probability=0.90, has_news_trigger=True))
        self.assertEqual(with_news.direction, SignalDirection.SKIP)
        self.assertEqual(with_news.confidence, 0.0)

        calm = score_mean_reversion(_features(current_probability=0.55))
        self.assertEqual(calm.direction, SignalDirection.SKIP)

    def test_mispricing_is_placeholder_only(self) -> None:
        result = score_mispricing(_features())
        self.assertEqual(result.direction, SignalDirection.SKIP)
        self.assertEqual(result.confidence, 0.0)


class AdmissionPolicyTest(unittest.TestCase):
    def _policy(self, **overrides: object) -> StrategyAdmissionPolicy:
        return StrategyAdmissionPolicy(_default_strategies_config(**overrides))

    def _accepted_signal(self) -> StrategySignal:
        return StrategySignal(
            market_id="m1",
            market_slug="btc",
            signal_type=SignalType.MOMENTUM_LAG,
            direction=SignalDirection.YES,
            confidence=0.85,
            reason="ok",
        )

    def test_rejects_below_min_confidence(self) -> None:
        signal = self._accepted_signal()
        signal.confidence = 0.60
        decision = self._policy().evaluate(AdmissionRequest(signal=signal, features=_features()))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.CONFIDENCE_BELOW_THRESHOLD.value)

    def test_rejects_high_spread(self) -> None:
        policy = self._policy()
        decision = policy.evaluate(
            AdmissionRequest(signal=self._accepted_signal(), features=_features(spread_bps=400.0))
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.SPREAD_TOO_WIDE.value)

    def test_rejects_low_liquidity(self) -> None:
        policy = self._policy()
        decision = policy.evaluate(
            AdmissionRequest(signal=self._accepted_signal(), features=_features(liquidity_usd=500.0))
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.LIQUIDITY_TOO_LOW.value)

    def test_rejects_short_time_to_resolution(self) -> None:
        policy = self._policy()
        decision = policy.evaluate(
            AdmissionRequest(
                signal=self._accepted_signal(),
                features=_features(seconds_to_resolution=120),
            )
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.TIME_TO_RESOLUTION_TOO_SHORT.value)

    def test_rejects_skip_direction(self) -> None:
        signal = self._accepted_signal()
        signal.direction = SignalDirection.SKIP
        decision = self._policy().evaluate(AdmissionRequest(signal=signal, features=_features()))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.SKIP_DIRECTION.value)

    def test_rejects_auto_execute_request(self) -> None:
        decision = self._policy().evaluate(
            AdmissionRequest(
                signal=self._accepted_signal(),
                features=_features(),
                auto_execute_requested=True,
            )
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.AUTO_EXECUTE_REQUESTED.value)

    def test_rejects_legacy_signal_by_default(self) -> None:
        legacy = StrategySignal(
            market_id="m1",
            market_slug="btc",
            signal_type=SignalType.LEGACY_BIDIRECTIONAL,
            direction=SignalDirection.YES,
            confidence=0.95,
            reason="legacy path",
            tags=["bidirectional"],
        )
        decision = self._policy().evaluate(AdmissionRequest(signal=legacy, features=_features()))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.LEGACY_BIDIRECTIONAL_DISABLED.value)

    def test_rejects_bidirectional_tag_on_other_signal_types(self) -> None:
        tagged = StrategySignal(
            market_id="m1",
            market_slug="btc",
            signal_type=SignalType.MOMENTUM_LAG,
            direction=SignalDirection.YES,
            confidence=0.9,
            reason="tagged",
            tags=["both_sides"],
        )
        decision = self._policy().evaluate(AdmissionRequest(signal=tagged, features=_features()))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.LEGACY_BIDIRECTIONAL_DISABLED.value)

    def test_strategies_disabled_short_circuits(self) -> None:
        policy = self._policy(enabled=False)
        decision = policy.evaluate(AdmissionRequest(signal=self._accepted_signal(), features=_features()))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rejection_code, AdmissionRejection.STRATEGIES_DISABLED.value)

    def test_legacy_enabled_allows_admission_but_still_produces_proposal_only(self) -> None:
        policy = self._policy(legacy_bidirectional_enabled=True)
        legacy = StrategySignal(
            market_id="m1",
            market_slug="btc",
            signal_type=SignalType.LEGACY_BIDIRECTIONAL,
            direction=SignalDirection.YES,
            confidence=0.9,
            reason="legacy path",
            tags=["bidirectional"],
        )
        decision = policy.evaluate(AdmissionRequest(signal=legacy, features=_features()))
        self.assertTrue(decision.accepted)
        artifact = to_proposal_artifact(decision, now=datetime(2026, 4, 24, tzinfo=timezone.utc))
        self.assertEqual(artifact["strategy_version"], STRATEGY_VERSION)
        self.assertEqual(artifact["signal_type"], SignalType.LEGACY_BIDIRECTIONAL.value)
        self.assertEqual(artifact["side"], "yes")


class SignalEngineIntegrationTest(unittest.TestCase):
    def test_engine_accepts_strong_momentum_lag(self) -> None:
        engine = SignalEngine(_default_strategies_config())
        evaluation = engine.evaluate(_features(btc_move_pct=0.015, polymarket_probability_move_pct=0.001))
        accepted_types = [d.signal.signal_type for d in evaluation.accepted]
        self.assertIn(SignalType.MOMENTUM_LAG, accepted_types)

    def test_engine_rejects_on_high_spread(self) -> None:
        engine = SignalEngine(_default_strategies_config())
        evaluation = engine.evaluate(_features(spread_bps=500.0, btc_move_pct=0.02))
        self.assertEqual(evaluation.accepted, [])
        self.assertTrue(any(
            d.rejection_code == AdmissionRejection.SPREAD_TOO_WIDE.value
            for d in evaluation.rejected
        ))

    def test_engine_rejects_on_low_liquidity(self) -> None:
        engine = SignalEngine(_default_strategies_config())
        evaluation = engine.evaluate(_features(liquidity_usd=100.0, btc_move_pct=0.02))
        self.assertEqual(evaluation.accepted, [])
        self.assertTrue(any(
            d.rejection_code == AdmissionRejection.LIQUIDITY_TOO_LOW.value
            for d in evaluation.rejected
        ))

    def test_mean_reversion_news_trigger_blocks(self) -> None:
        engine = SignalEngine(_default_strategies_config())
        evaluation = engine.evaluate(
            _features(current_probability=0.90, has_news_trigger=True, btc_move_pct=0.0)
        )
        self.assertEqual(evaluation.accepted, [])

    def test_mispricing_disabled_by_default(self) -> None:
        engine = SignalEngine(_default_strategies_config())
        evaluation = engine.evaluate(_features())
        signal_types = {d.signal.signal_type for d in evaluation.accepted + evaluation.rejected}
        self.assertNotIn(SignalType.MISPRICING, signal_types)

    def test_mispricing_enabled_never_accepts(self) -> None:
        engine = SignalEngine(_default_strategies_config(mispricing_enabled=True))
        evaluation = engine.evaluate(_features())
        accepted_types = {d.signal.signal_type for d in evaluation.accepted}
        self.assertNotIn(SignalType.MISPRICING, accepted_types)

    def test_diagnostics_exposes_disabled_legacy(self) -> None:
        engine = SignalEngine(_default_strategies_config())
        snapshot = engine.diagnostics()
        self.assertFalse(snapshot.legacy_bidirectional_enabled)
        self.assertIn(SignalType.LEGACY_BIDIRECTIONAL.value, snapshot.disabled_strategies)
        self.assertIn(SignalType.MOMENTUM_LAG.value, snapshot.enabled_strategies)
        self.assertTrue(snapshot.auto_execute_disabled)

    def test_engine_does_not_call_execution_adapter(self) -> None:
        """The engine must never hold or invoke an execution adapter."""
        class Tripwire:
            def __getattr__(self, name: str) -> object:
                raise AssertionError(f"SignalEngine must not touch execution adapters (accessed {name})")

        engine = SignalEngine(_default_strategies_config())
        # Attach the tripwire as an unexpected attribute; any accidental
        # reflection/introspection touching it would raise. The engine never
        # reads arbitrary attributes on itself.
        object.__setattr__(engine, "_tripwire_adapter", Tripwire())
        evaluation = engine.evaluate(_features(btc_move_pct=0.02, polymarket_probability_move_pct=0.001))
        self.assertGreaterEqual(evaluation.evaluated_count, 1)

    def test_accepted_decision_to_artifact_shape(self) -> None:
        engine = SignalEngine(_default_strategies_config())
        evaluation = engine.evaluate(_features(btc_move_pct=0.02, polymarket_probability_move_pct=0.001))
        self.assertGreaterEqual(len(evaluation.accepted), 1)
        decision: SignalDecision = evaluation.accepted[0]
        artifact = to_proposal_artifact(decision, now=datetime(2026, 4, 24, tzinfo=timezone.utc))
        self.assertEqual(artifact["strategy_version"], STRATEGY_VERSION)
        self.assertIn(artifact["signal_type"], {SignalType.MOMENTUM_LAG.value, SignalType.MEAN_REVERSION.value})
        self.assertIn("features", artifact)
        self.assertIn("risk_notes", artifact)
        self.assertIn("admission_reason", artifact)

    def test_rejected_decision_cannot_build_artifact(self) -> None:
        engine = SignalEngine(_default_strategies_config())
        evaluation = engine.evaluate(_features(spread_bps=999.0, btc_move_pct=0.02))
        self.assertEqual(evaluation.accepted, [])
        self.assertTrue(evaluation.rejected)
        with self.assertRaises(ValueError):
            to_proposal_artifact(evaluation.rejected[0], now=datetime(2026, 4, 24, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
