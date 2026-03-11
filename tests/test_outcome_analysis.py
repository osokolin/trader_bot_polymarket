from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from bot.adapters.polymarket.trading import SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import (
    AuditRepository,
    DecisionReviewRepository,
    ExecutionEvaluationRepository,
    OrderIntentRepository,
    OutcomeAnalysisRepository,
    ProbabilitySnapshotRepository,
    ProposalRepository,
)
from bot.utils.time import utc_now


class OutcomeAnalysisTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.crypto_market = Market(
            market_id="mkt_meta_crypto",
            title="Will BTC close above 95k?",
            category="crypto",
            liquidity_usd=25000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear",
            rules_confidence=0.98,
            tags=["crypto"],
            has_orderbook=True,
        )
        self.politics_market = Market(
            market_id="mkt_meta_politics",
            title="Will the incumbent party hold the senate?",
            category="politics",
            liquidity_usd=28000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear",
            rules_confidence=0.98,
            tags=["politics"],
            has_orderbook=True,
        )

    def test_grouped_outcome_analytics_and_cached_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            analysis, _, _, _, _, _ = self._build_fixture(tmp_dir)
            by_market = analysis.summarize_outcomes("market")
            self.assertEqual(len(by_market.groups), 2)
            crypto_group = next(item for item in by_market.groups if item.group_value == self.crypto_market.market_id)
            self.assertEqual(crypto_group.review_count, 1)
            self.assertEqual(crypto_group.evaluation_count, 1)
            self.assertIn("within_expected_range", crypto_group.verdict_counts)

            by_category = analysis.summarize_learning("category")
            self.assertEqual(len(by_category.groups), 2)
            categories = {item.group_value for item in by_category.groups}
            self.assertIn("crypto", categories)
            self.assertIn("politics", categories)

            by_source = analysis.summarize_outcomes("source_type")
            source_values = {item.group_value for item in by_source.groups}
            self.assertIn("official", source_values)
            self.assertIn("major_media", source_values)

            by_confidence = analysis.summarize_outcomes("confidence_band")
            confidence_values = {item.group_value for item in by_confidence.groups}
            self.assertIn("low", confidence_values)
            self.assertIn("medium", confidence_values)

            by_verdict = analysis.summarize_outcomes("verdict_type")
            verdict_values = {item.group_value for item in by_verdict.groups}
            self.assertIn("within_expected_range", verdict_values)
            self.assertIn("cancelled", verdict_values)

            cached = analysis.latest_snapshot("outcomes", "market")
            self.assertIsNotNone(cached)
            self.assertEqual(cached.group_by, "market")

    def test_cli_outcome_analysis_and_learning_summary_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._build_fixture(tmp_dir)
            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                outcomes_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "analysis",
                    "outcomes",
                    "--group-by",
                    "market",
                )
                self.assertIn("analysis_scope: outcomes", outcomes_output)
                self.assertIn("group_by: market", outcomes_output)
                self.assertIn(f"group={self.crypto_market.market_id}", outcomes_output)

                learning_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "analysis",
                    "learning-summary",
                    "--group-by",
                    "category",
                )
                self.assertIn("analysis_scope: learning_summary", learning_output)
                self.assertIn("group=crypto", learning_output)
                self.assertIn("group=politics", learning_output)

                latest_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "analysis",
                    "latest",
                    "--scope",
                    "outcomes",
                    "--group-by",
                    "market",
                )
                self.assertIn("analysis_scope: outcomes", latest_output)
                self.assertIn("group_count: 2", latest_output)
            finally:
                os.chdir(original_cwd)

    def _build_fixture(self, tmp_dir: str):
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
        evaluation_service = ExecutionEvaluationService(
            proposal_service,
            execution_service,
            ExecutionEvaluationRepository(connection),
        )
        analysis_service = OutcomeAnalysisService(
            proposal_service,
            DecisionReviewRepository(connection),
            ExecutionEvaluationRepository(connection),
            OutcomeAnalysisRepository(connection),
        )

        crypto_probability = ProbabilityEstimate(
            market_id=self.crypto_market.market_id,
            fair_probability=0.64,
            confidence=0.82,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )
        crypto_proposal = proposal_service.create(
            self.settings,
            proposal_service.proposal_engine.create_default_context(self.crypto_market, crypto_probability, 0.55),
        )
        crypto_approved = proposal_service.approve(
            self.settings,
            crypto_proposal.proposal_id,
            actor="alice",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            market=self.crypto_market,
            probability=crypto_probability,
            data_age_seconds=0,
        )
        crypto_intent = execution_service.create_order_intent(replace(crypto_approved, current_size_usd=40.0))
        execution_service.prepare_submission(crypto_intent.intent_id)
        execution_service.simulate_intent(crypto_intent.intent_id, actor="alice", best_bid=0.54, best_ask=0.55)
        review_service.create_for_proposal(crypto_proposal.proposal_id)
        evaluation_service.evaluate_intent(crypto_intent.intent_id)

        politics_probability = ProbabilityEstimate(
            market_id=self.politics_market.market_id,
            fair_probability=0.73,
            confidence=0.74,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL],
        )
        politics_proposal = proposal_service.create(
            self.settings,
            proposal_service.proposal_engine.create_default_context(self.politics_market, politics_probability, 0.55),
        )
        politics_approved = proposal_service.approve(
            self.settings,
            politics_proposal.proposal_id,
            actor="alice",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            market=self.politics_market,
            probability=politics_probability,
            data_age_seconds=0,
        )
        politics_intent = execution_service.create_order_intent(replace(politics_approved, current_size_usd=140.0))
        execution_service.prepare_submission(politics_intent.intent_id)
        execution_service.simulate_intent(politics_intent.intent_id, actor="alice", cancel_after_ms=500)
        review_service.create_for_proposal(politics_proposal.proposal_id)
        evaluation_service.evaluate_intent(politics_intent.intent_id)
        return (
            analysis_service,
            proposal_service,
            execution_service,
            review_service,
            evaluation_service,
            connection,
        )

    def _run_cli(self, *argv: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(list(argv))
        self.assertEqual(exit_code, 0)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
