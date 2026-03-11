from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from bot.adapters.polymarket.client import PolymarketTransportError
from bot.config.loader import load_settings
from bot.domain.enums import ProposalStatus, SourceType
from bot.domain.models import Market, OrderBookSnapshot, ProbabilityEstimate
from bot.services.market_data import RevalidationSnapshot
from bot.services.audit_log import AuditLogService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleError, ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, ProposalRepository
from bot.utils.time import utc_now


class ProposalLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))
        now = utc_now()
        self.market = Market(
            market_id="mkt_123",
            title="Will BTC ETF inflows rise this month?",
            category="crypto",
            liquidity_usd=12000,
            spread_pct=0.01,
            resolution_time=now + timedelta(days=3),
            rules_text="Clear",
            rules_confidence=0.95,
            tags=["crypto"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_123",
            fair_probability=0.64,
            confidence=0.84,
            model_agreement=2,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )

    class FakeSnapshotProvider:
        def __init__(
            self,
            market: Market,
            probability: ProbabilityEstimate,
            current_price: float,
            data_age_seconds: int,
            orderbook: OrderBookSnapshot | None = None,
        ) -> None:
            self.market = market
            self.probability = probability
            self.current_price = current_price
            self.data_age_seconds = data_age_seconds
            self.orderbook = orderbook

        def get_snapshot(self, proposal) -> RevalidationSnapshot:
            return RevalidationSnapshot(
                market=self.market,
                probability=self.probability,
                orderbook=self.orderbook,
                current_price=self.current_price,
                data_age_seconds=self.data_age_seconds,
            )

    class FailingSnapshotProvider:
        def get_snapshot(self, proposal) -> RevalidationSnapshot:
            raise PolymarketTransportError("network down")

    def _service(self) -> ProposalLifecycleService:
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()
        self.addCleanup(lambda: os.path.exists(temp_db.name) and os.unlink(temp_db.name))
        database = Database(Path(temp_db.name))
        database.initialize()
        connection = database.connect()
        self.addCleanup(connection.close)
        return ProposalLifecycleService(
            ProposalRepository(connection),
            AuditLogService(AuditRepository(connection)),
            ProposalEngine(),
        )

    def _service_with_provider(self, provider) -> ProposalLifecycleService:
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()
        self.addCleanup(lambda: os.path.exists(temp_db.name) and os.unlink(temp_db.name))
        database = Database(Path(temp_db.name))
        database.initialize()
        connection = database.connect()
        self.addCleanup(connection.close)
        return ProposalLifecycleService(
            ProposalRepository(connection),
            AuditLogService(AuditRepository(connection)),
            ProposalEngine(),
            snapshot_provider=provider,
        )

    def test_create_defaults_to_pending_manual_confirmation(self) -> None:
        service = self._service()
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        self.assertEqual(proposal.status, ProposalStatus.PENDING_MANUAL_CONFIRMATION)
        self.assertEqual(proposal.current_size_usd, proposal.recommended_size_usd)

    def test_edit_and_approve_flow_revalidates(self) -> None:
        service = self._service()
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        edited = service.edit_size(proposal.proposal_id, 30.0, actor="alice")
        edited = service.edit_price(edited.proposal_id, 0.56, actor="alice")
        approved = service.approve(
            self.settings,
            edited.proposal_id,
            actor="alice",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            market=self.market,
            probability=self.probability,
            data_age_seconds=5,
        )
        self.assertEqual(approved.status, ProposalStatus.APPROVED)
        self.assertEqual(approved.current_size_usd, 30.0)
        self.assertEqual(approved.current_limit_price, 0.56)
        self.assertEqual(approved.market_price, 0.56)

    def test_reject_flow_marks_cancelled(self) -> None:
        service = self._service()
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        rejected = service.reject(proposal.proposal_id, actor="bob", note="skip this market")
        self.assertEqual(rejected.status, ProposalStatus.CANCELLED)

    def test_expired_proposal_cannot_be_approved(self) -> None:
        service = self._service()
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        service.expire_stale(now=proposal.expires_at + timedelta(seconds=1))
        with self.assertRaises(ProposalLifecycleError):
            service.approve(
                self.settings,
                proposal.proposal_id,
                actor="alice",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
                market=self.market,
                probability=self.probability,
                data_age_seconds=5,
            )

    def test_revalidation_failure_moves_to_policy_rejected(self) -> None:
        service = self._service()
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        with self.assertRaises(ProposalLifecycleError):
            service.approve(
                self.settings,
                proposal.proposal_id,
                actor="alice",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
                market=self.market,
                probability=self.probability,
                data_age_seconds=999,
            )
        stored = service.get(proposal.proposal_id)
        self.assertEqual(stored.status, ProposalStatus.POLICY_REJECTED)
        self.assertEqual(stored.market_price, proposal.current_limit_price)

    def test_invalid_transitions_after_cancelled_are_rejected(self) -> None:
        service = self._service()
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        cancelled = service.reject(proposal.proposal_id, actor="bob")
        self.assertEqual(cancelled.status, ProposalStatus.CANCELLED)
        with self.assertRaises(ProposalLifecycleError):
            service.edit_size(cancelled.proposal_id, 10.0, actor="bob")
        with self.assertRaises(ProposalLifecycleError):
            service.approve(
                self.settings,
                cancelled.proposal_id,
                actor="bob",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
                market=self.market,
                probability=self.probability,
                data_age_seconds=0,
            )

    def test_invalid_transitions_after_approved_are_rejected(self) -> None:
        service = self._service()
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        approved = service.approve(
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
        with self.assertRaises(ProposalLifecycleError):
            service.reject(approved.proposal_id, actor="alice")
        with self.assertRaises(ProposalLifecycleError):
            service.edit_price(approved.proposal_id, 0.57, actor="alice")

    def test_approve_can_use_snapshot_provider(self) -> None:
        provider = self.FakeSnapshotProvider(
            market=self.market,
            probability=self.probability,
            current_price=0.54,
            data_age_seconds=3,
        )
        service = self._service_with_provider(provider)
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        approved = service.approve(
            self.settings,
            proposal.proposal_id,
            actor="alice",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
        )
        self.assertEqual(approved.status, ProposalStatus.APPROVED)
        self.assertEqual(approved.market_price, 0.54)

    def test_stale_orderbook_snapshot_is_rejected(self) -> None:
        orderbook = OrderBookSnapshot(
            market_id=self.market.market_id,
            best_bid=0.48,
            best_ask=0.52,
            midpoint=0.50,
            spread_pct=0.08,
            timestamp=utc_now() - timedelta(minutes=10),
        )
        provider = self.FakeSnapshotProvider(
            market=self.market,
            probability=self.probability,
            current_price=0.50,
            data_age_seconds=600,
            orderbook=orderbook,
        )
        service = self._service_with_provider(provider)
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        with self.assertRaises(ProposalLifecycleError):
            service.approve(
                self.settings,
                proposal.proposal_id,
                actor="alice",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
            )
        stored = service.get(proposal.proposal_id)
        self.assertEqual(stored.status, ProposalStatus.POLICY_REJECTED)

    def test_adapter_failure_fails_closed_and_keeps_pending(self) -> None:
        service = self._service_with_provider(self.FailingSnapshotProvider())
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        with self.assertRaises(ProposalLifecycleError):
            service.approve(
                self.settings,
                proposal.proposal_id,
                actor="alice",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
            )
        stored = service.get(proposal.proposal_id)
        self.assertEqual(stored.status, ProposalStatus.PENDING_MANUAL_CONFIRMATION)
        review = service.proposal_repository.connection.execute(
            "SELECT action FROM proposal_reviews WHERE proposal_id = ? ORDER BY created_at DESC LIMIT 1",
            (proposal.proposal_id,),
        ).fetchone()
        self.assertEqual(review[0], "snapshot_error")

    def test_fresh_probability_can_downgrade_to_policy_rejected(self) -> None:
        downgraded_probability = ProbabilityEstimate(
            market_id="mkt_123",
            fair_probability=0.56,
            confidence=0.84,
            model_agreement=2,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )
        provider = self.FakeSnapshotProvider(
            market=self.market,
            probability=downgraded_probability,
            current_price=0.54,
            data_age_seconds=3,
        )
        service = self._service_with_provider(provider)
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        with self.assertRaises(ProposalLifecycleError):
            service.approve(
                self.settings,
                proposal.proposal_id,
                actor="alice",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
            )
        stored = service.get(proposal.proposal_id)
        self.assertEqual(stored.status, ProposalStatus.POLICY_REJECTED)
        self.assertEqual(stored.fair_probability, 0.56)

    def test_audit_events_record_transitions(self) -> None:
        service = self._service()
        connection = service.proposal_repository.connection
        context = service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.55)
        proposal = service.create(self.settings, context)
        service.edit_size(proposal.proposal_id, 25.0, actor="alice")
        service.reject(proposal.proposal_id, actor="alice")
        events = connection.execute(
            "SELECT event_type FROM audit_events WHERE entity_id = ? ORDER BY created_at",
            (proposal.proposal_id,),
        ).fetchall()
        self.assertEqual(
            [row[0] for row in events],
            ["proposal_created", "proposal_edited", "proposal_rejected_manually"],
        )
