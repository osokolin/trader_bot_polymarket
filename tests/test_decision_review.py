from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bot.adapters.polymarket.trading import SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import (
    AuditRepository,
    DecisionReviewRepository,
    OrderIntentRepository,
    ProbabilitySnapshotRepository,
    ProposalRepository,
)
from bot.utils.time import utc_now


class DecisionReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.market = Market(
            market_id="mkt_review",
            title="Will ETH dominance decline by year end?",
            category="crypto",
            liquidity_usd=30000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear market rules",
            rules_confidence=0.98,
            tags=["crypto"],
            has_orderbook=True,
        )
        self.initial_probability = ProbabilityEstimate(
            market_id=self.market.market_id,
            fair_probability=0.62,
            confidence=0.82,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
            key_factors=["trend still supportive", "macro flows mixed"],
            source_count=2,
            confidence_components={"model": 0.82, "sources": 0.8},
            explanation="Baseline desk view with mixed macro flows.",
            source_inputs=[{"type": "official", "name": "Desk feed"}],
        )
        self.updated_probability = ProbabilityEstimate(
            market_id=self.market.market_id,
            fair_probability=0.68,
            confidence=0.76,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
            key_factors=["trend still supportive", "alts improving"],
            source_count=3,
            confidence_components={"model": 0.76, "sources": 0.85},
            explanation="Fresh research leans further in favor, with slightly lower confidence.",
            source_inputs=[
                {"type": "official", "name": "Desk feed"},
                {"type": "research", "name": "Alt basket note"},
            ],
        )

    def test_decision_review_composes_links_and_persists_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service, review_service, proposal, approved, intent = self._build_review_fixture(tmp_dir)
            review = review_service.create_for_proposal(approved.proposal_id)
            self.assertEqual(review.scope, "proposal")
            self.assertEqual(review.market_id, self.market.market_id)
            self.assertEqual(review.proposal.proposal_id, approved.proposal_id)
            self.assertEqual(review.probability_snapshot.proposal_id, approved.proposal_id)
            self.assertIsNotNone(review.probability_drift.previous_snapshot)
            self.assertEqual(review.latest_intent.intent_id, intent.intent_id)
            self.assertIsNotNone(review.latest_execution)
            self.assertEqual(review.confidence_outcome, "confidence_degraded")
            self.assertEqual(review.probability_outcome, "probability_moved_in_favor")
            self.assertEqual(review.execution_outcome, "execution_unfavorable")
            persisted = review_service.latest_persisted_for_proposal(approved.proposal_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.proposal_id, approved.proposal_id)
            self.assertEqual(persisted.intent_id, intent.intent_id)
            self.assertEqual(persisted.execution_outcome, "execution_unfavorable")
            self.assertIn("probability_drift", persisted.payload)
            self.assertIn("summary", persisted.payload)
            self.assertEqual(
                service.latest_probability_snapshot_for_market(self.market.market_id).proposal_id,
                approved.proposal_id,
            )

    def test_cli_decision_review_by_proposal_and_market_exposes_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _, review_service, _, approved, _ = self._build_review_fixture(tmp_dir)
            review_service.create_for_proposal(approved.proposal_id)
            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                proposal_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "decision-review",
                    approved.proposal_id,
                )
                self.assertIn("decision_review_id:", proposal_output)
                self.assertIn("scope: proposal", proposal_output)
                self.assertIn("confidence_outcome: confidence_degraded", proposal_output)
                self.assertIn("probability_outcome: probability_moved_in_favor", proposal_output)
                self.assertIn("execution_outcome: execution_unfavorable", proposal_output)

                market_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "markets",
                    "decision-review",
                    self.market.market_id,
                )
                self.assertIn("scope: market", market_output)
                self.assertIn(f"market_id: {self.market.market_id}", market_output)
                self.assertIn("latest_intent_status:", market_output)
                self.assertIn("summary: confidence=confidence_degraded", market_output)
            finally:
                os.chdir(original_cwd)

            connection = Database(Path(tmp_dir) / "bot.db").connect()
            try:
                persisted = DecisionReviewRepository(connection).latest_for_market(self.market.market_id)
                self.assertIsNotNone(persisted)
                self.assertEqual(persisted.market_id, self.market.market_id)
            finally:
                connection.close()

    def _build_review_fixture(self, tmp_dir: str):
        database = Database(Path(tmp_dir) / "bot.db")
        database.initialize()
        connection = database.connect()
        self.addCleanup(connection.close)
        proposal_service = ProposalLifecycleService(
            ProposalRepository(connection),
            AuditLogService(AuditRepository(connection)),
            ProposalEngine(),
            probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
        )
        execution_service = ExecutionPipelineService(
            self.settings,
            SemiAutoExecutionAdapter(),
            OrderIntentRepository(connection),
            AuditLogService(AuditRepository(connection)),
        )
        review_service = DecisionReviewService(
            proposal_service,
            execution_service,
            DecisionReviewRepository(connection),
        )
        proposal = proposal_service.create(
            self.settings,
            proposal_service.proposal_engine.create_default_context(self.market, self.initial_probability, 0.55),
        )
        approved = proposal_service.approve(
            self.settings,
            proposal.proposal_id,
            actor="reviewer",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            market=self.market,
            probability=self.updated_probability,
            data_age_seconds=2,
        )
        intent = execution_service.create_order_intent(approved)
        execution_service.prepare_submission(intent.intent_id)
        execution_service.simulate_intent(intent.intent_id, actor="reviewer")
        return proposal_service, review_service, proposal, approved, intent

    def _run_cli(self, *argv: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(list(argv))
        self.assertEqual(exit_code, 0)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
