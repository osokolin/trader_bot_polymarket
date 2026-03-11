from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import IntentStatus, SourceType
from bot.domain.models import Market, ProbabilityEstimate, SimulatedExecution, SimulatedFillEvent
from bot.services.audit_log import AuditLogService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import (
    AuditRepository,
    ExecutionEvaluationRepository,
    OrderIntentRepository,
    ProposalRepository,
)
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class ExecutionEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.market = Market(
            market_id="mkt_eval",
            title="Will BTC hold above 90k?",
            category="crypto",
            liquidity_usd=20000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear",
            rules_confidence=0.98,
            tags=["crypto"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id=self.market.market_id,
            fair_probability=0.64,
            confidence=0.84,
            model_agreement=2,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )

    def test_execution_evaluation_verdicts_cover_complete_partial_expired_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            proposal_service, pipeline, evaluator, repository = self._build_services(tmp_dir)
            better_intent = self._prepared_intent(proposal_service, pipeline, "mkt_better", 40.0)
            self._save_execution(
                repository,
                better_intent.intent_id,
                IntentStatus.SIMULATED_FILLED,
                reference_price=0.55,
                simulated_price=0.546,
                filled_size_usd=40.0,
                latency_ms=200,
                completion_reason="fully_filled",
                timeline_count=1,
            )
            better = evaluator.evaluate_intent(better_intent.intent_id)
            self.assertEqual(better.verdict, "better_than_expected")

            worse_intent = self._prepared_intent(proposal_service, pipeline, "mkt_worse", 40.0)
            self._save_execution(
                repository,
                worse_intent.intent_id,
                IntentStatus.SIMULATED_FILLED,
                reference_price=0.55,
                simulated_price=0.558,
                filled_size_usd=40.0,
                latency_ms=650,
                completion_reason="fully_filled",
                timeline_count=1,
            )
            worse = evaluator.evaluate_intent(worse_intent.intent_id)
            self.assertEqual(worse.verdict, "worse_than_expected")

            within_intent = self._prepared_intent(proposal_service, pipeline, "mkt_within", 40.0)
            self._save_execution(
                repository,
                within_intent.intent_id,
                IntentStatus.SIMULATED_FILLED,
                reference_price=0.55,
                simulated_price=0.551,
                filled_size_usd=40.0,
                latency_ms=250,
                completion_reason="fully_filled",
                timeline_count=1,
            )
            within = evaluator.evaluate_intent(within_intent.intent_id)
            self.assertEqual(within.verdict, "within_expected_range")

            partial_intent = self._prepared_intent(proposal_service, pipeline, "mkt_partial", 80.0)
            self._save_execution(
                repository,
                partial_intent.intent_id,
                IntentStatus.SIMULATED_PARTIALLY_FILLED,
                reference_price=0.55,
                simulated_price=0.551,
                filled_size_usd=32.0,
                latency_ms=500,
                completion_reason="partial_fill_open",
                timeline_count=1,
            )
            partial = evaluator.evaluate_intent(partial_intent.intent_id)
            self.assertEqual(partial.verdict, "partially_filled")

            expired_intent = self._prepared_intent(proposal_service, pipeline, "mkt_expired", 120.0)
            pipeline.simulate_intent(expired_intent.intent_id, actor="alice", ttl_ms=500)
            expired = evaluator.evaluate_intent(expired_intent.intent_id)
            self.assertEqual(expired.verdict, "expired")

            cancelled_intent = self._prepared_intent(proposal_service, pipeline, "mkt_cancelled", 140.0)
            pipeline.simulate_intent(cancelled_intent.intent_id, actor="alice", cancel_after_ms=500)
            cancelled = evaluator.evaluate_intent(cancelled_intent.intent_id)
            self.assertEqual(cancelled.verdict, "cancelled")

            persisted = evaluator.latest_persisted_for_intent(cancelled_intent.intent_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.verdict, "cancelled")
            self.assertIn("actual_completion_reason", persisted.payload)

    def test_cli_execution_evaluation_by_intent_and_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            proposal_service, pipeline, evaluator, _ = self._build_services(tmp_dir)
            intent = self._prepared_intent(proposal_service, pipeline, "mkt_cli_eval", 40.0)
            pipeline.simulate_intent(intent.intent_id, actor="cli", best_bid=0.54, best_ask=0.55, base_latency_ms=200)
            evaluator.evaluate_intent(intent.intent_id)
            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                intent_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "evaluate",
                    intent.intent_id,
                )
                self.assertIn("execution_evaluation_id:", intent_output)
                self.assertIn("intent_id:", intent_output)
                self.assertIn("verdict:", intent_output)
                self.assertIn("actual_completion_reason:", intent_output)

                proposal_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "execution-evaluation",
                    intent.proposal_id,
                )
                self.assertIn(f"proposal_id: {intent.proposal_id}", proposal_output)
                self.assertIn("timeline_event_count:", proposal_output)
                self.assertIn("summary:", proposal_output)
            finally:
                os.chdir(original_cwd)

    def _build_services(self, tmp_dir: str):
        database = Database(Path(tmp_dir) / "bot.db")
        database.initialize()
        connection = database.connect()
        self.addCleanup(connection.close)
        proposal_service = ProposalLifecycleService(
            ProposalRepository(connection),
            AuditLogService(AuditRepository(connection)),
            ProposalEngine(),
        )
        repository = OrderIntentRepository(connection)
        pipeline = ExecutionPipelineService(
            self.settings,
            SemiAutoExecutionAdapter(),
            repository,
            AuditLogService(AuditRepository(connection)),
            paper_execution_adapter=PaperExecutionAdapter(),
        )
        evaluator = ExecutionEvaluationService(
            proposal_service,
            pipeline,
            ExecutionEvaluationRepository(connection),
        )
        return proposal_service, pipeline, evaluator, repository

    def _prepared_intent(
        self,
        proposal_service: ProposalLifecycleService,
        pipeline: ExecutionPipelineService,
        market_id: str,
        size_usd: float,
    ):
        market = replace(self.market, market_id=market_id, title=f"{market_id} title")
        proposal = proposal_service.create(
            self.settings,
            proposal_service.proposal_engine.create_default_context(market, self.probability, 0.55),
        )
        approved = proposal_service.approve(
            self.settings,
            proposal.proposal_id,
            actor="alice",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            market=market,
            probability=self.probability,
            data_age_seconds=0,
        )
        sized = replace(approved, current_size_usd=size_usd)
        proposal_service.proposal_repository.save(sized)
        intent = pipeline.create_order_intent(sized)
        pipeline.prepare_submission(intent.intent_id)
        return intent

    def _save_execution(
        self,
        repository: OrderIntentRepository,
        intent_id: str,
        status: IntentStatus,
        reference_price: float,
        simulated_price: float,
        filled_size_usd: float,
        latency_ms: int,
        completion_reason: str,
        timeline_count: int,
    ) -> None:
        now = utc_now()
        execution_id = new_id("simexec")
        repository.save_execution(
            SimulatedExecution(
                execution_id=execution_id,
                intent_id=intent_id,
                status=status,
                accepted=True,
                order_id=f"paper_{intent_id}",
                reference_price=reference_price,
                best_bid=reference_price - 0.01,
                best_ask=reference_price,
                simulated_price=simulated_price,
                slippage_bps=round(((simulated_price - reference_price) / reference_price) * 10000, 2),
                filled_size_usd=filled_size_usd,
                fill_timestamp=now,
                latency_ms=latency_ms,
                completion_reason=completion_reason,
                message="saved for evaluation test",
                created_at=now,
            )
        )
        events = [
            SimulatedFillEvent(
                event_id=new_id("sfill"),
                execution_id=execution_id,
                intent_id=intent_id,
                event_type="fill",
                fragment_index=index,
                price=simulated_price,
                size_usd=round(filled_size_usd / timeline_count, 2),
                remaining_size_usd=round(max(0.0, filled_size_usd - (filled_size_usd / timeline_count) * index), 2),
                latency_ms=int(latency_ms / timeline_count) * index,
                event_timestamp=now,
                message="fragment",
            )
            for index in range(1, timeline_count + 1)
        ]
        repository.save_fill_events(events)

    def _run_cli(self, *argv: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(list(argv))
        self.assertEqual(exit_code, 0)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
