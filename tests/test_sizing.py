from __future__ import annotations

import unittest
from pathlib import Path

from bot.config.loader import load_settings
from bot.services.sizing import SizingEngine, SizingInput


class SizingTest(unittest.TestCase):
    def test_size_respects_unresolved_exposure_limit(self) -> None:
        settings = load_settings(Path("config"))
        engine = SizingEngine()
        result = engine.size(
            settings,
            SizingInput(
                confidence=0.9,
                min_confidence=settings.entry_rules.min_confidence,
                edge=0.12,
                min_edge=settings.entry_rules.min_edge_pct,
                theme_exposure_usd=0,
                unresolved_exposure_usd=340,
                liquidity_usd=10000,
            ),
        )
        self.assertLessEqual(result.recommended_size_usd, 10.0)
        self.assertLessEqual(result.recommended_size_usd, result.max_allowed_size_usd)

    def test_low_confidence_reduces_size(self) -> None:
        settings = load_settings(Path("config"))
        engine = SizingEngine()
        strong = engine.size(
            settings,
            SizingInput(
                confidence=0.95,
                min_confidence=settings.entry_rules.min_confidence,
                edge=0.10,
                min_edge=settings.entry_rules.min_edge_pct,
                theme_exposure_usd=0,
                unresolved_exposure_usd=0,
                liquidity_usd=10000,
            ),
        )
        weak = engine.size(
            settings,
            SizingInput(
                confidence=0.72,
                min_confidence=settings.entry_rules.min_confidence,
                edge=0.10,
                min_edge=settings.entry_rules.min_edge_pct,
                theme_exposure_usd=0,
                unresolved_exposure_usd=0,
                liquidity_usd=10000,
            ),
        )
        self.assertLess(weak.recommended_size_usd, strong.recommended_size_usd)


if __name__ == "__main__":
    unittest.main()

