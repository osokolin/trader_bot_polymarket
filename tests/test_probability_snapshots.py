from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import SourceType
from bot.domain.models import EvidenceRecord, Market, OrderBookSnapshot, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.probability_engine import EdgeAdjustedProbabilityProvider
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, ProbabilitySnapshotRepository, ProposalRepository
from bot.utils.time import utc_now


class ProbabilitySnapshotsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.market = Market(
            market_id="mkt_prob",
            title="Will unemployment stay below 5%?",
            category="crypto",
            liquidity_usd=21000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear rules",
            rules_confidence=0.98,
            tags=["macro"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_prob",
            fair_probability=0.63,
            confidence=0.82,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
            key_factors=["official data stable", "spread remains tight"],
            source_count=2,
            confidence_components={"model": 0.82, "liquidity": 1.0, "spread": 0.99},
            explanation="Combined official macro prints with a tight market spread.",
            source_inputs=[
                {"type": "official", "name": "BLS", "weight": 0.6},
                {"type": "major_media", "name": "Reuters", "weight": 0.4},
            ],
            evidence_records=[
                EvidenceRecord(
                    source_id="bls",
                    source_name="BLS",
                    source_type=SourceType.OFFICIAL,
                    weight=0.6,
                    contribution=0.49,
                    summary="Official macro print supports the thesis.",
                    supports_trade=True,
                ),
                EvidenceRecord(
                    source_id="reuters",
                    source_name="Reuters",
                    source_type=SourceType.MAJOR_MEDIA,
                    weight=0.4,
                    contribution=0.33,
                    summary="Major media coverage confirms stability.",
                    supports_trade=True,
                ),
            ],
            source_type_contributions={"official": 0.49, "major_media": 0.33},
        )

    def test_probability_snapshot_persistence_and_latest_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                service = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                    probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
                )
                proposal = service.create(
                    self.settings,
                    service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = service.approve(
                    self.settings,
                    proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=4,
                )
                proposal_snapshot = service.latest_probability_snapshot_for_proposal(approved.proposal_id)
                market_snapshot = service.latest_probability_snapshot_for_market(self.market.market_id)
                self.assertEqual(proposal_snapshot.market_id, self.market.market_id)
                self.assertEqual(proposal_snapshot.proposal_id, approved.proposal_id)
                self.assertEqual(proposal_snapshot.probability.source_count, 2)
                self.assertEqual(proposal_snapshot.probability.key_factors, self.probability.key_factors)
                self.assertIn("model", proposal_snapshot.probability.confidence_components)
                self.assertEqual(len(proposal_snapshot.probability.evidence_records), 2)
                self.assertEqual(proposal_snapshot.probability.evidence_records[0].source_name, "BLS")
                self.assertAlmostEqual(proposal_snapshot.probability.source_type_contributions["official"], 0.49, places=4)
                self.assertEqual(market_snapshot.research_summary.summary, self.probability.explanation)
                self.assertEqual(market_snapshot.research_summary.source_count, 2)
                self.assertGreaterEqual(len(market_snapshot.research_summary.thesis_points), 1)
                self.assertTrue(any("BLS" in item for item in market_snapshot.research_summary.evidence_summary))
            finally:
                connection.close()

    def test_provider_builds_weighted_evidence_and_source_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                service = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                    probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
                )
                proposal = service.create(
                    self.settings,
                    service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = service.approve(
                    self.settings,
                    proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=1,
                )
                estimate = EdgeAdjustedProbabilityProvider().get_probability(
                    approved,
                    self.market,
                    OrderBookSnapshot(
                        market_id=self.market.market_id,
                        best_bid=0.56,
                        best_ask=0.58,
                        midpoint=0.57,
                        spread_pct=0.02,
                        timestamp=utc_now(),
                    ),
                )
                self.assertEqual(len(estimate.evidence_records), 2)
                self.assertAlmostEqual(sum(item.weight for item in estimate.evidence_records), 1.0, places=3)
                self.assertIn("official", estimate.source_type_contributions)
                self.assertIn("major_media", estimate.source_type_contributions)
                self.assertGreater(estimate.source_type_contributions["official"], 0.0)
            finally:
                connection.close()

    def test_probability_snapshot_comparison_and_drift_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                service = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                    probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
                )
                proposal = service.create(
                    self.settings,
                    service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = service.approve(
                    self.settings,
                    proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=4,
                )
                updated_probability = ProbabilityEstimate(
                    market_id=self.market.market_id,
                    fair_probability=0.68,
                    confidence=0.86,
                    model_agreement=3,
                    trusted_source_present=True,
                    source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
                    key_factors=["official data stable", "new research source added"],
                    source_count=3,
                    confidence_components={"model": 0.86, "liquidity": 1.0, "spread": 0.98},
                    explanation="Updated with an additional research source and tighter conviction.",
                    source_inputs=[
                        {"type": "official", "name": "BLS", "weight": 0.5},
                        {"type": "major_media", "name": "Reuters", "weight": 0.25},
                        {"type": "research", "name": "Desk model", "weight": 0.25},
                    ],
                    evidence_records=[
                        EvidenceRecord(
                            source_id="bls",
                            source_name="BLS",
                            source_type=SourceType.OFFICIAL,
                            weight=0.5,
                            contribution=0.43,
                            summary="Official data still supports the thesis.",
                            supports_trade=True,
                        ),
                        EvidenceRecord(
                            source_id="reuters",
                            source_name="Reuters",
                            source_type=SourceType.MAJOR_MEDIA,
                            weight=0.25,
                            contribution=0.21,
                            summary="Media confirmation remains supportive.",
                            supports_trade=True,
                        ),
                        EvidenceRecord(
                            source_id="desk_model",
                            source_name="Desk model",
                            source_type=SourceType.RESEARCH,
                            weight=0.25,
                            contribution=0.22,
                            summary="Internal research added incremental support.",
                            supports_trade=True,
                        ),
                    ],
                    source_type_contributions={"official": 0.43, "major_media": 0.21, "research": 0.22},
                )
                second_proposal = service.create(
                    self.settings,
                    service.proposal_engine.create_default_context(self.market, self.probability, 0.57),
                )
                second_approved = service.approve(
                    self.settings,
                    second_proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=updated_probability,
                    data_age_seconds=2,
                )
                proposal_drift = service.compare_probability_snapshots_for_proposal(second_approved.proposal_id)
                self.assertAlmostEqual(proposal_drift.fair_probability_delta or 0.0, 0.05, places=4)
                self.assertAlmostEqual(proposal_drift.confidence_delta or 0.0, 0.04, places=4)
                self.assertEqual(proposal_drift.source_count_delta, 1)
                self.assertIsNotNone(proposal_drift.previous_snapshot)
                self.assertIn("source_count_delta", proposal_drift.drift_summary)
                self.assertIn("research", proposal_drift.source_type_contribution_deltas)
                self.assertIn("research:Desk model", proposal_drift.added_evidence_sources)

                market_drift = service.compare_probability_snapshots_for_market(self.market.market_id)
                self.assertEqual(market_drift.latest_snapshot.proposal_id, second_approved.proposal_id)
                self.assertEqual(market_drift.previous_snapshot.proposal_id, second_approved.proposal_id)
                self.assertAlmostEqual(market_drift.fair_probability_delta or 0.0, 0.05, places=4)
                self.assertAlmostEqual(market_drift.confidence_delta or 0.0, 0.04, places=4)
                self.assertEqual(market_drift.source_count_delta, 1)
                self.assertIn("new research source added", market_drift.added_key_factors)
                self.assertIn("spread remains tight", market_drift.removed_key_factors)
                self.assertIn("model", market_drift.confidence_component_deltas)
                self.assertIn("research", market_drift.source_type_contribution_deltas)
                self.assertIn("research:Desk model", market_drift.added_evidence_sources)
            finally:
                connection.close()

    def test_cli_probability_and_research_inspection_by_proposal_and_market(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                service = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                    probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
                )
                proposal = service.create(
                    self.settings,
                    service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                service.approve(
                    self.settings,
                    proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=3,
                )
                updated_probability = ProbabilityEstimate(
                    market_id=self.market.market_id,
                    fair_probability=0.68,
                    confidence=0.86,
                    model_agreement=3,
                    trusted_source_present=True,
                    source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
                    key_factors=["official data stable", "new research source added"],
                    source_count=3,
                    confidence_components={"model": 0.86, "liquidity": 1.0, "spread": 0.98},
                    explanation="Updated with an additional research source and tighter conviction.",
                    source_inputs=[
                        {"type": "official", "name": "BLS", "weight": 0.5},
                        {"type": "major_media", "name": "Reuters", "weight": 0.25},
                        {"type": "research", "name": "Desk model", "weight": 0.25},
                    ],
                    evidence_records=[
                        EvidenceRecord(
                            source_id="bls",
                            source_name="BLS",
                            source_type=SourceType.OFFICIAL,
                            weight=0.5,
                            contribution=0.43,
                            summary="Official data still supports the thesis.",
                            supports_trade=True,
                        ),
                        EvidenceRecord(
                            source_id="reuters",
                            source_name="Reuters",
                            source_type=SourceType.MAJOR_MEDIA,
                            weight=0.25,
                            contribution=0.21,
                            summary="Media confirmation remains supportive.",
                            supports_trade=True,
                        ),
                        EvidenceRecord(
                            source_id="desk_model",
                            source_name="Desk model",
                            source_type=SourceType.RESEARCH,
                            weight=0.25,
                            contribution=0.22,
                            summary="Internal research added incremental support.",
                            supports_trade=True,
                        ),
                    ],
                    source_type_contributions={"official": 0.43, "major_media": 0.21, "research": 0.22},
                )
                second = service.create(
                    self.settings,
                    service.proposal_engine.create_default_context(self.market, updated_probability, 0.57),
                )
                service.approve(
                    self.settings,
                    second.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=updated_probability,
                    data_age_seconds=2,
                )
            finally:
                connection.close()

            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                proposal_probability = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "probability",
                    proposal.proposal_id,
                )
                self.assertIn("fair_probability:", proposal_probability)
                self.assertIn("source_count: 2", proposal_probability)
                self.assertIn("confidence_components:", proposal_probability)
                self.assertIn("source_type_contributions:", proposal_probability)
                self.assertIn("BLS", proposal_probability)

                proposal_research = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "research",
                    proposal.proposal_id,
                )
                self.assertIn("research_summary:", proposal_research)
                self.assertIn("research_key_factors:", proposal_research)
                self.assertIn("evidence_summary:", proposal_research)

                market_probability = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "markets",
                    "probability",
                    self.market.market_id,
                )
                self.assertIn(f"market_id: {self.market.market_id}", market_probability)
                self.assertIn("explanation:", market_probability)
                self.assertIn("evidence_records:", market_probability)

                market_research = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "markets",
                    "research",
                    self.market.market_id,
                )
                self.assertIn("thesis_points:", market_research)
                self.assertIn("risk_points:", market_research)
                self.assertIn("evidence_summary:", market_research)

                proposal_compare = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "compare",
                    proposal.proposal_id,
                )
                self.assertIn("drift_scope: proposal", proposal_compare)
                self.assertIn("drift_summary:", proposal_compare)
                self.assertIn("source_type_contribution_deltas:", proposal_compare)
                self.assertIn("added_evidence_sources:", proposal_compare)

                market_compare = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "markets",
                    "compare",
                    self.market.market_id,
                )
                self.assertIn("drift_scope: market", market_compare)
                self.assertIn("fair_probability_delta", market_compare)
                self.assertIn("source_type_contribution_deltas:", market_compare)
            finally:
                os.chdir(original_cwd)

    def _run_cli(self, *argv: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(list(argv))
        self.assertEqual(exit_code, 0)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
