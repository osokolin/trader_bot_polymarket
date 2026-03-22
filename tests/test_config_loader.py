from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from bot.config.loader import ConfigError, load_settings, parse_yaml


class ConfigLoaderTest(unittest.TestCase):
    def test_load_settings_merges_base_and_profile(self) -> None:
        settings = load_settings(Path("config"), profile="conservative")
        self.assertEqual(settings.mode.value, "semi_auto")
        self.assertEqual(settings.position_limits.max_position_pct, 0.04)
        self.assertEqual(settings.market_filters.min_liquidity_usd, 3000)
        self.assertTrue(settings.approvals.manual_approval_required)

    def test_environment_override_wins_for_mode(self) -> None:
        original = os.environ.get("BOT_MODE")
        os.environ["BOT_MODE"] = "paper"
        try:
            settings = load_settings(Path("config"))
        finally:
            if original is None:
                os.environ.pop("BOT_MODE", None)
            else:
                os.environ["BOT_MODE"] = original
        self.assertEqual(settings.mode.value, "paper")

    def test_yaml_parser_handles_nested_maps_and_lists(self) -> None:
        parsed = parse_yaml(
            """
            root:
              enabled: true
              values:
                - one
                - two
            """
        )
        self.assertEqual(parsed["root"]["enabled"], True)
        self.assertEqual(parsed["root"]["values"], ["one", "two"])

    def test_invalid_yaml_raises(self) -> None:
        with self.assertRaises(ConfigError):
            parse_yaml("root: [1, 2")

    def test_invalid_ratio_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for file_name in ("balanced.yaml", "sources.yaml", "whitelist.yaml", "blacklist.yaml"):
                (tmp_path / file_name).write_text((Path("config") / file_name).read_text())
            invalid = (Path("config") / "base.yaml").read_text().replace("reserve_ratio: 0.20", "reserve_ratio: 1.20")
            (tmp_path / "base.yaml").write_text(invalid)
            with self.assertRaises(ConfigError):
                load_settings(tmp_path)

    def test_polymarket_gateway_is_disabled_by_default(self) -> None:
        settings = load_settings(Path("config"))
        self.assertFalse(settings.polymarket_gateway.enable_polymarket_gateway)
        self.assertTrue(settings.polymarket_gateway.dry_run)

    def test_polymarket_gateway_live_submission_is_rejected_in_semi_auto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for file_name in ("balanced.yaml", "sources.yaml", "whitelist.yaml", "blacklist.yaml"):
                (tmp_path / file_name).write_text((Path("config") / file_name).read_text())
            invalid = (Path("config") / "base.yaml").read_text().replace(
                "allow_live_order_submission: false",
                "allow_live_order_submission: true",
            )
            (tmp_path / "base.yaml").write_text(invalid)
            with self.assertRaises(ConfigError):
                load_settings(tmp_path)


if __name__ == "__main__":
    unittest.main()
