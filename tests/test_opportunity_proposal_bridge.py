from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from bot.config.loader import load_settings
from bot.domain.enums import ProposalStatus, SourceType
from bot.domain.models import (
    Market,
    MarketDataSnapshot,
    OpportunityCandidate,
    OpportunityDraftAction,
    OpportunityDraftResult,
    OrderBookSnapshot,
    ProbabilityEstimate,
)
from bot.cli.app import main
from bot.services.audit_log import AuditLogService
from bot.services.opportunity_proposal_bridge import OpportunityProposalBridgeService
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, OrderIntentRepository, ProposalRepository
from bot.utils.time import utc_now


class _FakeMarketDataService:
    def __init__(self, snapshots: dict[str, MarketDataSnapshot]) -> None:
        self.snapshots = snapshots

    def inspect_snapshot(self, market_id: str, refresh: bool = False) -> MarketDataSnapshot:
        return self.snapshots[market_id]


class _FakeScannerService:
    def __init__(
        self,
        opportunities: list[OpportunityCandidate],
        snapshots: dict[str, MarketDataSnapshot],
        probability_by_market: dict[str, ProbabilityEstimate],
    ) -> None:
        self.opportunities = opportunities
        self.market_data_service = _FakeMarketDataService(snapshots)
        self.probability_by_market = probability_by_market
        self.calls: list[tuple[float | None, float | None, int]] = []

    def scan(self, settings, min_edge=None, min_liquidity=None, limit=20):
        self.calls.append((min_edge, min_liquidity, limit))
        return type(
            "ScanResult",
            (),
            {
                "opportunities": self.opportunities[:limit],
                "scanned_count": len(self.opportunities),
                "skipped_count": 0,
                "warning_messages": [],
            },
        )()

    def estimate_probability(self, snapshot: MarketDataSnapshot) -> ProbabilityEstimate:
        return self.probability_by_market[snapshot.market_id]


def _build_market(market_id: str) -> Market:
    now = utc_now()
    return Market(
        market_id=market_id,
        title=f"Market {market_id}",
        category="crypto",
        liquidity_usd=12000.0,
        spread_pct=0.01,
        resolution_time=now + timedelta(days=10),
        rules_text="Clear rules",
        rules_confidence=0.95,
        has_orderbook=True,
    )


def _build_snapshot(market: Market, midpoint: float = 0.45) -> MarketDataSnapshot:
    now = utc_now()
    return MarketDataSnapshot(
        snapshot_id=f"snap_{market.market_id}",
        market_id=market.market_id,
        asset_id=f"asset_{market.market_id}",
        market=market,
        orderbook=OrderBookSnapshot(
            market_id=market.market_id,
            best_bid=round(midpoint - 0.01, 4),
            best_ask=round(midpoint + 0.01, 4),
            midpoint=midpoint,
            spread_pct=0.01,
            timestamp=now,
        ),
        observed_at=now,
        fetched_at=now,
        source="inspection",
        stale=False,
        data_age_seconds=0,
        reference_price=0.60,
        pricing_metadata={},
        websocket_payload={},
    )


def _build_probability(market_id: str) -> ProbabilityEstimate:
    return ProbabilityEstimate(
        market_id=market_id,
        fair_probability=0.525,
        confidence=0.82,
        model_agreement=1,
        trusted_source_present=False,
        source_types=[SourceType.RESEARCH],
    )


class OpportunityProposalBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))
        relaxed_entry = replace(
            self.settings.entry_rules,
            min_model_agreement=1,
            require_trusted_source=False,
            min_confidence=0.5,
        )
        relaxed_ai = replace(
            self.settings.ai_policy,
            allowed_source_types=[*self.settings.ai_policy.allowed_source_types, SourceType.RESEARCH],
        )
        self.relaxed_settings = replace(self.settings, entry_rules=relaxed_entry, ai_policy=relaxed_ai)

        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()
        self.addCleanup(lambda: os.path.exists(temp_db.name) and os.unlink(temp_db.name))
        database = Database(Path(temp_db.name))
        database.initialize()
        self.connection = database.connect()
        self.addCleanup(self.connection.close)
        self.proposal_service = ProposalLifecycleService(
            ProposalRepository(self.connection),
            AuditLogService(AuditRepository(self.connection)),
        )
        self.intent_repository = OrderIntentRepository(self.connection)

    def test_create_draft_from_scanner_result(self) -> None:
        market = _build_market("m1")
        opportunity = OpportunityCandidate(
            market_id="m1",
            market_title=market.title,
            category=market.category,
            market_price=0.45,
            fair_probability=0.525,
            edge=0.075,
            confidence=0.82,
            liquidity_usd=market.liquidity_usd,
            source="inspection",
        )
        scanner = _FakeScannerService(
            [opportunity],
            {"m1": _build_snapshot(market)},
            {"m1": _build_probability("m1")},
        )
        bridge = OpportunityProposalBridgeService(scanner, self.proposal_service)  # type: ignore[arg-type]

        result = bridge.draft_opportunities(self.relaxed_settings)

        self.assertEqual(len(result.created), 1)
        self.assertEqual(len(result.skipped), 0)
        stored = self.proposal_service.list_proposals()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].status, ProposalStatus.PENDING_MANUAL_CONFIRMATION)
        self.assertEqual(self.intent_repository.list_all(), [])

    def test_skip_duplicate_proposal_for_same_market(self) -> None:
        market = _build_market("m1")
        probability = _build_probability("m1")
        context = self.proposal_service.proposal_engine.create_default_context(market, probability, 0.45)
        existing = self.proposal_service.create(self.relaxed_settings, context)

        opportunity = OpportunityCandidate(
            market_id="m1",
            market_title=market.title,
            category=market.category,
            market_price=0.45,
            fair_probability=0.525,
            edge=0.075,
            confidence=0.82,
            liquidity_usd=market.liquidity_usd,
            source="inspection",
        )
        scanner = _FakeScannerService(
            [opportunity],
            {"m1": _build_snapshot(market)},
            {"m1": probability},
        )
        bridge = OpportunityProposalBridgeService(scanner, self.proposal_service)  # type: ignore[arg-type]

        result = bridge.draft_opportunities(self.relaxed_settings)

        self.assertEqual(len(result.created), 0)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0].reason, "duplicate_active_proposal")
        self.assertEqual(result.skipped[0].proposal_id, existing.proposal_id)
        self.assertEqual(len(self.proposal_service.list_proposals()), 1)

    def test_bridge_respects_filters_passed_to_scanner(self) -> None:
        market = _build_market("m1")
        scanner = _FakeScannerService(
            [],
            {"m1": _build_snapshot(market)},
            {"m1": _build_probability("m1")},
        )
        bridge = OpportunityProposalBridgeService(scanner, self.proposal_service)  # type: ignore[arg-type]

        bridge.draft_opportunities(self.relaxed_settings, min_edge=0.08, min_liquidity=5000.0, limit=7)

        self.assertEqual(scanner.calls, [(0.08, 5000.0, 7)])

    def test_safe_proposal_state_only(self) -> None:
        market = _build_market("m1")
        opportunity = OpportunityCandidate(
            market_id="m1",
            market_title=market.title,
            category=market.category,
            market_price=0.45,
            fair_probability=0.525,
            edge=0.075,
            confidence=0.82,
            liquidity_usd=market.liquidity_usd,
            source="inspection",
        )
        scanner = _FakeScannerService(
            [opportunity],
            {"m1": _build_snapshot(market)},
            {"m1": _build_probability("m1")},
        )
        bridge = OpportunityProposalBridgeService(scanner, self.proposal_service)  # type: ignore[arg-type]

        result = bridge.draft_opportunities(self.settings)

        self.assertEqual(len(result.created), 1)
        proposal = self.proposal_service.latest_proposal_state(result.created[0].proposal_id)
        self.assertIn(proposal.status, {ProposalStatus.PENDING_MANUAL_CONFIRMATION, ProposalStatus.POLICY_REJECTED})
        self.assertNotEqual(proposal.status, ProposalStatus.APPROVED)

    def test_cli_output_is_readable(self) -> None:
        fake_result = OpportunityDraftResult(
            created=[
                OpportunityDraftAction(
                    market_id="m1",
                    market_title="Market m1",
                    action="created",
                    reason="draft_created",
                    proposal_id="proposal_1",
                    proposal_status=ProposalStatus.PENDING_MANUAL_CONFIRMATION,
                    edge=0.08,
                )
            ],
            skipped=[
                OpportunityDraftAction(
                    market_id="m2",
                    market_title="Market m2",
                    action="skipped",
                    reason="duplicate_active_proposal",
                    proposal_id="proposal_existing",
                    proposal_status=ProposalStatus.PENDING_MANUAL_CONFIRMATION,
                    edge=0.07,
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "cli.db"
            with patch.dict(os.environ, {"BOT_DATABASE_URL": f"sqlite:///{db_path}"}, clear=False), patch(
                "bot.cli.app.OpportunityProposalBridgeService"
            ) as bridge_cls:
                bridge_cls.return_value.draft_opportunities.return_value = fake_result
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    exit_code = main(["--config-dir", "config", "markets", "draft-opportunities", "--limit", "5"])
                output = buffer.getvalue()
                self.assertEqual(exit_code, 0)
                self.assertIn("Opportunity proposal bridge", output)
                self.assertIn("created_count: 1", output)
                self.assertIn("skipped_count: 1", output)
                self.assertIn("action=created | market_id=m1", output)
                self.assertIn("action=skipped | market_id=m2", output)
                self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
