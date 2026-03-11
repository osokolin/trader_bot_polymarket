from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.config.loader import load_settings
from bot.domain.enums import IntentStatus, ProposalStatus, SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.execution_pipeline import ExecutionBoundaryError, ExecutionPipelineService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, OrderIntentRepository, ProposalRepository
from bot.utils.time import utc_now


class ExecutionPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))
        now = utc_now()
        self.market = Market(
            market_id="mkt_1",
            title="Will BTC close above 100k?",
            category="crypto",
            liquidity_usd=12000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear",
            rules_confidence=0.95,
            tags=["crypto"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_1",
            fair_probability=0.64,
            confidence=0.84,
            model_agreement=2,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )

    def test_build_intent_requires_approved_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                )
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.create_order_intent(proposal)
            finally:
                connection.close()

    def test_prepare_submission_for_approved_intent_is_non_autonomous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                self.assertEqual(approved.status, ProposalStatus.APPROVED)
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                )
                intent = pipeline.create_order_intent(approved)
                outcome = pipeline.prepare_submission(intent.intent_id)
                self.assertTrue(outcome.accepted)
                stored_intent = pipeline.order_intent_repository.get(intent.intent_id)
                self.assertEqual(stored_intent.status, IntentStatus.PREPARED)
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.submit_intent(intent.intent_id)
                stored_intent = pipeline.order_intent_repository.get(intent.intent_id)
                self.assertEqual(stored_intent.status, IntentStatus.SUBMISSION_DISABLED)
            finally:
                connection.close()

    def test_simulated_execution_records_fill_details_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                intent = pipeline.create_order_intent(approved)
                pipeline.prepare_submission(intent.intent_id)
                outcome = pipeline.simulate_intent(intent.intent_id, actor="alice")
                stored_intent = pipeline.order_intent_repository.get(intent.intent_id)
                self.assertEqual(outcome.stage, IntentStatus.SIMULATED_FILLED.value)
                self.assertEqual(stored_intent.status, IntentStatus.SIMULATED_FILLED)
                self.assertEqual(outcome.reference_price, approved.current_limit_price)
                self.assertIsNotNone(outcome.simulated_price)
                self.assertIsNotNone(outcome.slippage_bps)
                self.assertEqual(outcome.filled_size_usd, approved.current_size_usd)
                self.assertIsNotNone(outcome.fill_timestamp)
                self.assertEqual(len(pipeline.list_execution_history(intent.intent_id)), 1)
                self.assertEqual(len(pipeline.list_execution_timeline(intent.intent_id)), 1)
                reviews = pipeline.list_review_history(intent.intent_id)
                self.assertEqual(reviews[0]["action"], "simulate_execution")
                self.assertIn("slippage_bps", reviews[0]["payload_json"])
                self.assertIn("latency_ms", reviews[0]["payload_json"])
                audits = pipeline.list_audit_history(intent.intent_id)
                self.assertEqual(audits[0]["event_type"], "order_execution_simulated")
                self.assertIn("reference_price", audits[0]["payload_json"])
            finally:
                connection.close()

    def test_bid_ask_aware_partial_fill_completion_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                medium = replace(approved, current_size_usd=75.0)
                ProposalRepository(connection).save(medium)
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                intent = pipeline.create_order_intent(medium)
                pipeline.prepare_submission(intent.intent_id)
                outcome = pipeline.simulate_intent(
                    intent.intent_id,
                    actor="alice",
                    best_bid=0.53,
                    best_ask=0.57,
                    base_latency_ms=300,
                )
                saved = pipeline.latest_simulated_execution(intent.intent_id)
                timeline = pipeline.list_execution_timeline(intent.intent_id)
                self.assertEqual(outcome.stage, IntentStatus.SIMULATED_FILLED.value)
                self.assertEqual(saved.reference_price, 0.57)
                self.assertEqual(saved.best_bid, 0.53)
                self.assertEqual(saved.best_ask, 0.57)
                self.assertEqual(len(timeline), 2)
                self.assertGreater(timeline[1].event_timestamp, timeline[0].event_timestamp)
                self.assertEqual(timeline[-1].remaining_size_usd, 0.0)
            finally:
                connection.close()

    def test_simulation_expiry_and_cancel_scenarios_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                expiring = replace(approved, current_size_usd=120.0)
                ProposalRepository(connection).save(expiring)
                expire_intent = pipeline.create_order_intent(expiring)
                pipeline.prepare_submission(expire_intent.intent_id)
                expired = pipeline.simulate_intent(expire_intent.intent_id, actor="alice", ttl_ms=500)
                self.assertEqual(expired.stage, IntentStatus.SIMULATED_EXPIRED.value)
                self.assertEqual(pipeline.latest_intent_state(expire_intent.intent_id).status, IntentStatus.SIMULATED_EXPIRED)
                self.assertEqual(pipeline.latest_simulated_execution(expire_intent.intent_id).completion_reason, "ttl_expired")

                second = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(replace(self.market, market_id="mkt_cancel"), self.probability, 0.55),
                )
                second_approved = lifecycle.approve(
                    self.settings,
                    second.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=replace(self.market, market_id="mkt_cancel"),
                    probability=self.probability,
                    data_age_seconds=0,
                )
                cancelled_proposal = replace(second_approved, current_size_usd=140.0)
                ProposalRepository(connection).save(cancelled_proposal)
                cancel_intent = pipeline.create_order_intent(cancelled_proposal)
                pipeline.prepare_submission(cancel_intent.intent_id)
                cancelled = pipeline.simulate_intent(cancel_intent.intent_id, actor="alice", cancel_after_ms=700)
                self.assertEqual(cancelled.stage, IntentStatus.SIMULATED_CANCELLED.value)
                self.assertEqual(
                    pipeline.latest_simulated_execution(cancel_intent.intent_id).completion_reason,
                    "operator_cancelled",
                )
                self.assertEqual(len(pipeline.list_execution_timeline(cancel_intent.intent_id)), 1)
            finally:
                connection.close()

    def test_invalid_prepare_transitions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                )
                first = pipeline.create_order_intent(approved)
                second = pipeline.create_order_intent(approved, supersede_existing=True)
                superseded = pipeline.order_intent_repository.get(first.intent_id)
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.prepare_submission(superseded.intent_id)
                blocked = replace(superseded, status=IntentStatus.BLOCKED)
                pipeline.order_intent_repository.save(blocked)
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.prepare_submission(blocked.intent_id)
                prepared = pipeline.prepare_submission(second.intent_id)
                self.assertTrue(prepared.accepted)
            finally:
                connection.close()

    def test_invalid_submit_transitions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                )
                created = pipeline.create_order_intent(approved)
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.submit_intent(created.intent_id)
                pipeline.prepare_submission(created.intent_id)
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.submit_intent(created.intent_id)
                disabled = pipeline.order_intent_repository.get(created.intent_id)
                self.assertEqual(disabled.status, IntentStatus.SUBMISSION_DISABLED)
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.submit_intent(created.intent_id)
            finally:
                connection.close()

    def test_simulation_requires_prepared_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                created = pipeline.create_order_intent(approved)
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.simulate_intent(created.intent_id, actor="alice")
                pipeline.prepare_submission(created.intent_id)
                pipeline.simulate_intent(created.intent_id, actor="alice")
                with self.assertRaisesRegex(ExecutionBoundaryError, "cannot be simulated again"):
                    pipeline.simulate_intent(created.intent_id, actor="alice")
            finally:
                connection.close()

    def test_simulation_summary_reporting_and_latest_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                first_proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                first_approved = lifecycle.approve(
                    self.settings,
                    first_proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                first_intent = pipeline.create_order_intent(first_approved)
                pipeline.prepare_submission(first_intent.intent_id)
                first_outcome = pipeline.simulate_intent(first_intent.intent_id, actor="alice")

                second_market = replace(self.market, market_id="mkt_2", title="Will ETH close above 7k?")
                second_proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(second_market, self.probability, 0.55),
                )
                second_approved = lifecycle.approve(
                    self.settings,
                    second_proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=second_market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                oversized = replace(second_approved, current_size_usd=75.0)
                ProposalRepository(connection).save(oversized)
                second_intent = pipeline.create_order_intent(oversized)
                pipeline.prepare_submission(second_intent.intent_id)
                second_outcome = pipeline.simulate_intent(second_intent.intent_id, actor="alice")

                first_summary = pipeline.simulation_summary_for_intent(first_intent.intent_id)
                self.assertEqual(first_summary.execution_count, 1)
                self.assertEqual(first_summary.filled_count, 1)
                self.assertEqual(first_summary.partial_fill_count, 0)

                overall_summary = pipeline.simulation_summary_overall()
                self.assertEqual(overall_summary.execution_count, 2)
                self.assertEqual(overall_summary.filled_count, 2)
                self.assertEqual(overall_summary.partial_fill_count, 0)
                self.assertEqual(
                    overall_summary.total_filled_size_usd,
                    round((first_outcome.filled_size_usd or 0.0) + (second_outcome.filled_size_usd or 0.0), 2),
                )
                self.assertIsNotNone(overall_summary.average_slippage_bps)
                latest = pipeline.latest_simulated_execution_overall()
                self.assertIsNotNone(latest)
                self.assertEqual(latest.intent_id, second_intent.intent_id)
            finally:
                connection.close()

    def test_duplicate_active_intent_requires_supersede(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                )
                first_intent = pipeline.create_order_intent(approved)
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.create_order_intent(approved)
                second_intent = pipeline.create_order_intent(approved, supersede_existing=True)
                superseded = pipeline.order_intent_repository.get(first_intent.intent_id)
                self.assertEqual(superseded.status, IntentStatus.SUPERSEDED)
                self.assertEqual(superseded.superseded_by_intent_id, second_intent.intent_id)
            finally:
                connection.close()

    def test_stale_approved_proposal_cannot_create_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = lifecycle.approve(
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
                stale = ProposalRepository(connection).get(approved.proposal_id)
                stale.expires_at = utc_now().replace(year=utc_now().year - 1)
                ProposalRepository(connection).save(stale)
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                )
                with self.assertRaises(ExecutionBoundaryError):
                    pipeline.create_order_intent(stale)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
