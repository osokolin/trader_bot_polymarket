from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.config.loader import load_settings
from bot.domain.enums import ProposalStatus, SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, OrderIntentRepository, ProposalRepository
from bot.utils.time import utc_now


class OperatorObservabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))
        now = utc_now()
        self.market = Market(
            market_id="mkt_obs",
            title="Will CPI print below expectations?",
            category="crypto",
            liquidity_usd=10000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear",
            rules_confidence=0.95,
            tags=["macro"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_obs",
            fair_probability=0.65,
            confidence=0.85,
            model_agreement=2,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )

    def test_latest_state_and_histories_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                proposal_service = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                execution_service = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                proposal = proposal_service.create(
                    self.settings,
                    proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = proposal_service.approve(
                    self.settings,
                    proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                intent = execution_service.create_order_intent(approved)
                execution_service.prepare_submission(intent.intent_id)
                execution_service.simulate_intent(intent.intent_id, actor="alice")
                self.assertEqual(proposal_service.latest_proposal_state(proposal.proposal_id).status, ProposalStatus.APPROVED)
                self.assertIsNone(execution_service.latest_active_intent(proposal.proposal_id))
                self.assertGreaterEqual(len(proposal_service.list_review_history(proposal.proposal_id)), 2)
                self.assertGreaterEqual(len(proposal_service.list_audit_history(proposal.proposal_id)), 2)
                self.assertGreaterEqual(len(execution_service.list_review_history(intent.intent_id)), 3)
                self.assertGreaterEqual(len(execution_service.list_audit_history(intent.intent_id)), 3)
                self.assertEqual(len(execution_service.list_execution_history(intent.intent_id)), 1)
            finally:
                connection.close()

    def test_filtering_helpers_return_expected_subsets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                proposal_service = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                execution_service = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                proposal = proposal_service.create(
                    self.settings,
                    proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = proposal_service.approve(
                    self.settings,
                    proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                intent = execution_service.create_order_intent(approved)
                execution_service.prepare_submission(intent.intent_id)
                with self.assertRaises(Exception):
                    execution_service.submit_intent(intent.intent_id)
                self.assertGreaterEqual(len(proposal_service.list_active_proposals()), 1)
                self.assertGreaterEqual(len(proposal_service.list_approved_proposals()), 1)
                self.assertIsNotNone(proposal_service.latest_approved_proposal())
                self.assertEqual(len(execution_service.list_active_intents()), 0)
                self.assertGreaterEqual(len(execution_service.list_terminal_intents()), 1)
                self.assertIsNotNone(execution_service.latest_terminal_intent())
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
