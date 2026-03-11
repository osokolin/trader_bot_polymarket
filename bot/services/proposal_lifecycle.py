from __future__ import annotations

from dataclasses import replace

from bot.config.models import Settings
from bot.domain.enums import ProposalStatus
from bot.domain.models import (
    Market,
    ProbabilityDrift,
    ProbabilityEstimate,
    ProbabilitySnapshot,
    ResearchSummary,
    TradeProposal,
)
from bot.adapters.polymarket.client import PolymarketAdapterError
from bot.services.audit_log import AuditLogService
from bot.services.market_data import ApprovalSnapshotProvider, RevalidationSnapshot
from bot.services.proposal_engine import ProposalContext, ProposalEngine
from bot.storage.repositories import ProbabilitySnapshotRepository, ProposalRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class ProposalLifecycleError(ValueError):
    pass


class ProposalLifecycleService:
    def __init__(
        self,
        proposal_repository: ProposalRepository,
        audit_log: AuditLogService,
        proposal_engine: ProposalEngine | None = None,
        snapshot_provider: ApprovalSnapshotProvider | None = None,
        probability_snapshot_repository: ProbabilitySnapshotRepository | None = None,
    ) -> None:
        self.proposal_repository = proposal_repository
        self.audit_log = audit_log
        self.proposal_engine = proposal_engine or ProposalEngine()
        self.snapshot_provider = snapshot_provider
        self.probability_snapshot_repository = probability_snapshot_repository

    def create(self, settings: Settings, context: ProposalContext) -> TradeProposal:
        proposal = self.proposal_engine.create_proposal(settings, context)
        self.proposal_repository.save(proposal)
        self._persist_probability_snapshot(
            proposal.proposal_id,
            context.market,
            context.probability,
            context.current_price,
            context.data_age_seconds,
            context.thesis,
            context.risks,
            proposal.created_at,
        )
        self._record_review(proposal.proposal_id, "create", "system", None, {"status": proposal.status.value}, proposal.created_at)
        self.audit_log.log(
            "proposal_created",
            proposal.proposal_id,
            f"Proposal created with status {proposal.status.value}",
            {"status": proposal.status.value},
            created_at=proposal.created_at,
        )
        return proposal

    def list_proposals(self) -> list[TradeProposal]:
        return self.proposal_repository.list_all()

    def list_active_proposals(self) -> list[TradeProposal]:
        return self.proposal_repository.list_by_statuses(
            [ProposalStatus.PENDING_MANUAL_CONFIRMATION, ProposalStatus.APPROVED]
        )

    def list_approved_proposals(self) -> list[TradeProposal]:
        return self.proposal_repository.list_by_statuses([ProposalStatus.APPROVED])

    def latest_proposal_state(self, proposal_id: str) -> TradeProposal:
        proposal = self.proposal_repository.latest_state(proposal_id)
        if proposal is None:
            raise ProposalLifecycleError(f"Unknown proposal: {proposal_id}")
        return proposal

    def list_review_history(self, proposal_id: str) -> list:
        return self.proposal_repository.list_reviews(proposal_id)

    def list_audit_history(self, proposal_id: str) -> list:
        return self.audit_log.repository.list_for_entity(proposal_id)

    def latest_approved_proposal(self) -> TradeProposal | None:
        return self.proposal_repository.latest_by_statuses([ProposalStatus.APPROVED])

    def latest_probability_snapshot_for_proposal(self, proposal_id: str) -> ProbabilitySnapshot:
        if self.probability_snapshot_repository is None:
            raise ProposalLifecycleError("Probability snapshot repository is not configured")
        snapshot = self.probability_snapshot_repository.latest_for_proposal(proposal_id)
        if snapshot is None:
            raise ProposalLifecycleError(f"No probability snapshot for proposal: {proposal_id}")
        return snapshot

    def latest_probability_snapshot_for_market(self, market_id: str) -> ProbabilitySnapshot:
        if self.probability_snapshot_repository is None:
            raise ProposalLifecycleError("Probability snapshot repository is not configured")
        snapshot = self.probability_snapshot_repository.latest_for_market(market_id)
        if snapshot is None:
            raise ProposalLifecycleError(f"No probability snapshot for market: {market_id}")
        return snapshot

    def compare_probability_snapshots_for_proposal(self, proposal_id: str) -> ProbabilityDrift:
        if self.probability_snapshot_repository is None:
            raise ProposalLifecycleError("Probability snapshot repository is not configured")
        snapshots = self.probability_snapshot_repository.list_for_proposal(proposal_id, limit=2)
        if not snapshots:
            raise ProposalLifecycleError(f"No probability snapshot for proposal: {proposal_id}")
        return self._build_probability_drift("proposal", snapshots[0], snapshots[1] if len(snapshots) > 1 else None)

    def compare_probability_snapshots_for_market(self, market_id: str) -> ProbabilityDrift:
        if self.probability_snapshot_repository is None:
            raise ProposalLifecycleError("Probability snapshot repository is not configured")
        snapshots = self.probability_snapshot_repository.list_for_market(market_id, limit=2)
        if not snapshots:
            raise ProposalLifecycleError(f"No probability snapshot for market: {market_id}")
        return self._build_probability_drift("market", snapshots[0], snapshots[1] if len(snapshots) > 1 else None)

    def get(self, proposal_id: str) -> TradeProposal:
        proposal = self.proposal_repository.get(proposal_id)
        if proposal is None:
            raise ProposalLifecycleError(f"Unknown proposal: {proposal_id}")
        return proposal

    def expire_stale(self, now=None) -> list[TradeProposal]:
        now = now or utc_now()
        expired_items: list[TradeProposal] = []
        for proposal in self.proposal_repository.list_all():
            if proposal.status == ProposalStatus.PENDING_MANUAL_CONFIRMATION and proposal.expires_at <= now:
                expired = replace(proposal, status=ProposalStatus.CANCELLED, updated_at=now)
                self.proposal_repository.save(expired)
                self._record_review(expired.proposal_id, "expire", "system", None, {}, now)
                self.audit_log.log(
                    "proposal_expired",
                    expired.proposal_id,
                    "Proposal TTL expired",
                    {"previous_status": proposal.status.value, "status": expired.status.value},
                    created_at=now,
                )
                expired_items.append(expired)
        return expired_items

    def edit_size(self, proposal_id: str, amount: float, actor: str) -> TradeProposal:
        proposal = self.get(proposal_id)
        if proposal.status != ProposalStatus.PENDING_MANUAL_CONFIRMATION:
            raise ProposalLifecycleError("Only pending proposals can be edited")
        if amount <= 0 or amount > proposal.max_allowed_size_usd:
            raise ProposalLifecycleError("Edited size must be positive and within max allowed size")
        transition_at = utc_now()
        updated = replace(proposal, current_size_usd=round(amount, 2), updated_at=transition_at)
        self.proposal_repository.save(updated)
        self._record_review(updated.proposal_id, "edit_size", actor, None, {"current_size_usd": updated.current_size_usd}, transition_at)
        self.audit_log.log(
            "proposal_edited",
            updated.proposal_id,
            "Proposal size edited",
            {"actor": actor, "current_size_usd": updated.current_size_usd},
            created_at=transition_at,
        )
        return updated

    def edit_price(self, proposal_id: str, price: float, actor: str) -> TradeProposal:
        proposal = self.get(proposal_id)
        if proposal.status != ProposalStatus.PENDING_MANUAL_CONFIRMATION:
            raise ProposalLifecycleError("Only pending proposals can be edited")
        if not 0 < price <= 1:
            raise ProposalLifecycleError("Edited price must be between 0 and 1")
        transition_at = utc_now()
        updated = replace(proposal, current_limit_price=round(price, 4), updated_at=transition_at)
        self.proposal_repository.save(updated)
        self._record_review(updated.proposal_id, "edit_price", actor, None, {"current_limit_price": updated.current_limit_price}, transition_at)
        self.audit_log.log(
            "proposal_edited",
            updated.proposal_id,
            "Proposal price edited",
            {"actor": actor, "current_limit_price": updated.current_limit_price},
            created_at=transition_at,
        )
        return updated

    def reject(self, proposal_id: str, actor: str, note: str | None = None) -> TradeProposal:
        proposal = self.get(proposal_id)
        if proposal.status != ProposalStatus.PENDING_MANUAL_CONFIRMATION:
            raise ProposalLifecycleError("Only pending proposals can be rejected")
        transition_at = utc_now()
        updated = replace(proposal, status=ProposalStatus.CANCELLED, updated_at=transition_at)
        self.proposal_repository.save(updated)
        self._record_review(updated.proposal_id, "reject", actor, note, {}, transition_at)
        self.audit_log.log(
            "proposal_rejected_manually",
            updated.proposal_id,
            "Proposal rejected manually",
            {"actor": actor, "note": note, "status": updated.status.value},
            created_at=transition_at,
        )
        return updated

    def approve(
        self,
        settings: Settings,
        proposal_id: str,
        actor: str,
        open_positions: int,
        unresolved_exposure_usd: float,
        theme_exposure_usd: float,
        market: Market | None = None,
        probability: ProbabilityEstimate | None = None,
        data_age_seconds: int | None = None,
    ) -> TradeProposal:
        proposal = self.get(proposal_id)
        transition_at = utc_now()
        if proposal.status != ProposalStatus.PENDING_MANUAL_CONFIRMATION:
            raise ProposalLifecycleError("Only pending proposals can be approved")
        if proposal.expires_at <= transition_at:
            expired = replace(proposal, status=ProposalStatus.CANCELLED, updated_at=transition_at)
            self.proposal_repository.save(expired)
            self._record_review(expired.proposal_id, "expire", "system", None, {}, transition_at)
            self.audit_log.log(
                "proposal_expired",
                expired.proposal_id,
                "Proposal expired before approval",
                {"actor": actor},
                created_at=transition_at,
            )
            raise ProposalLifecycleError("Proposal approval TTL expired")

        snapshot = self._resolve_snapshot(
            proposal=proposal,
            actor=actor,
            market=market,
            probability=probability,
            data_age_seconds=data_age_seconds,
        )
        context = ProposalContext(
            market=snapshot.market,
            probability=snapshot.probability,
            current_price=snapshot.current_price,
            open_positions=open_positions,
            unresolved_exposure_usd=unresolved_exposure_usd,
            theme_exposure_usd=theme_exposure_usd,
            order_type=settings.entry_rules.order_type,
            data_age_seconds=snapshot.data_age_seconds,
            thesis=proposal.thesis,
            risks=proposal.risks,
            now=transition_at,
            edge=snapshot.probability.fair_probability - snapshot.current_price,
            proposed_size_usd=proposal.current_size_usd,
        )
        decision = self.proposal_engine.composite_policy.evaluate(settings, context)
        if not decision.allowed:
            rejected = replace(
                proposal,
                market_price=snapshot.current_price,
                fair_probability=snapshot.probability.fair_probability,
                confidence=snapshot.probability.confidence,
                model_agreement=snapshot.probability.model_agreement,
                trusted_source_present=snapshot.probability.trusted_source_present,
                source_types=snapshot.probability.source_types,
                status=ProposalStatus.POLICY_REJECTED,
                updated_at=transition_at,
                policy_decision=decision,
            )
            self.proposal_repository.save(rejected)
            self._record_review(
                rejected.proposal_id,
                "revalidate_reject",
                actor,
                None,
                self._revalidation_payload(snapshot, {"reasons": [item.value for item in decision.reasons]}),
                transition_at,
            )
            self.audit_log.log(
                "proposal_revalidation_failed",
                rejected.proposal_id,
                "Proposal failed pre-trade revalidation",
                self._revalidation_payload(
                    snapshot,
                    {"actor": actor, "reasons": [item.value for item in decision.reasons]},
                ),
                created_at=transition_at,
            )
            raise ProposalLifecycleError("Proposal failed pre-trade revalidation")

        approved = replace(
            proposal,
            market_price=snapshot.current_price,
            fair_probability=snapshot.probability.fair_probability,
            confidence=snapshot.probability.confidence,
            model_agreement=snapshot.probability.model_agreement,
            trusted_source_present=snapshot.probability.trusted_source_present,
            source_types=snapshot.probability.source_types,
            status=ProposalStatus.APPROVED,
            updated_at=transition_at,
            policy_decision=decision,
        )
        self.proposal_repository.save(approved)
        self._persist_probability_snapshot(
            approved.proposal_id,
            snapshot.market,
            snapshot.probability,
            snapshot.current_price,
            snapshot.data_age_seconds,
            approved.thesis,
            approved.risks,
            transition_at,
        )
        self._record_review(
            approved.proposal_id,
            "approve",
            actor,
            None,
            self._revalidation_payload(
                snapshot,
                {
                    "current_size_usd": approved.current_size_usd,
                    "current_limit_price": approved.current_limit_price,
                },
            ),
            transition_at,
        )
        self.audit_log.log(
            "proposal_approved_manually",
            approved.proposal_id,
            "Proposal approved after revalidation",
            self._revalidation_payload(
                snapshot,
                {"actor": actor, "status": approved.status.value},
            ),
            created_at=transition_at,
        )
        return approved

    def _record_review(
        self,
        proposal_id: str,
        action: str,
        actor: str,
        note: str | None,
        payload: dict[str, object],
        created_at,
    ) -> None:
        self.proposal_repository.save_review(
            review_id=new_id("review"),
            proposal_id=proposal_id,
            action=action,
            actor=actor,
            note=note,
            payload=payload,
            created_at=created_at.isoformat(),
        )

    def _resolve_snapshot(
        self,
        proposal: TradeProposal,
        actor: str,
        market: Market | None,
        probability: ProbabilityEstimate | None,
        data_age_seconds: int | None,
    ) -> RevalidationSnapshot:
        if self.snapshot_provider is not None:
            try:
                return self.snapshot_provider.get_snapshot(proposal)
            except PolymarketAdapterError as exc:
                self._record_review(
                    proposal.proposal_id,
                    "snapshot_error",
                    actor,
                    str(exc),
                    {"error_type": exc.__class__.__name__},
                    transition_at := utc_now(),
                )
                self.audit_log.log(
                    "proposal_revalidation_snapshot_failed",
                    proposal.proposal_id,
                    "Snapshot retrieval failed during approval",
                    {"actor": actor, "error": str(exc), "error_type": exc.__class__.__name__},
                    created_at=transition_at,
                )
                raise ProposalLifecycleError("Approval failed because fresh market data could not be retrieved") from exc
        if market is None or probability is None:
            raise ProposalLifecycleError("Approval requires market/probability context when no snapshot provider is configured")
        return RevalidationSnapshot(
            market=market,
            probability=probability,
            orderbook=None,
            current_price=proposal.current_limit_price,
            data_age_seconds=data_age_seconds or 0,
        )

    def _revalidation_payload(
        self,
        snapshot: RevalidationSnapshot,
        extra: dict[str, object],
    ) -> dict[str, object]:
        payload = {
            "revalidated_market_price": snapshot.current_price,
            "revalidated_fair_probability": snapshot.probability.fair_probability,
            "revalidated_confidence": snapshot.probability.confidence,
            "revalidated_data_age_seconds": snapshot.data_age_seconds,
        }
        if snapshot.market_snapshot_id is not None:
            payload["revalidated_market_snapshot_id"] = snapshot.market_snapshot_id
        if snapshot.snapshot_source is not None:
            payload["revalidated_market_snapshot_source"] = snapshot.snapshot_source
        if snapshot.last_trade_price is not None:
            payload["revalidated_last_trade_price"] = snapshot.last_trade_price
        if snapshot.orderbook is not None:
            payload["revalidated_orderbook_timestamp"] = snapshot.orderbook.timestamp.isoformat()
            payload["revalidated_spread_pct"] = snapshot.orderbook.spread_pct
        payload.update(extra)
        return payload

    def _persist_probability_snapshot(
        self,
        proposal_id: str | None,
        market: Market,
        probability: ProbabilityEstimate,
        current_price: float,
        data_age_seconds: int,
        thesis: list[str],
        risks: list[str],
        created_at,
    ) -> None:
        if self.probability_snapshot_repository is None:
            return
        research_summary = ResearchSummary(
            market_id=market.market_id,
            proposal_id=proposal_id,
            summary=probability.explanation or "Probability estimate recorded for operator inspection.",
            key_factors=probability.key_factors,
            thesis_points=thesis,
            risk_points=risks,
            source_count=probability.source_count,
            evidence_summary=[
                (
                    f"{item.source_type.value}:{item.source_name} "
                    f"weight={item.weight:.2f} contribution={item.contribution:.4f} "
                    f"supports_trade={item.supports_trade}"
                )
                for item in probability.evidence_records
            ],
        )
        self.probability_snapshot_repository.save(
            ProbabilitySnapshot(
                snapshot_id=new_id("psnap"),
                market_id=market.market_id,
                proposal_id=proposal_id,
                probability=probability,
                research_summary=research_summary,
                current_price=current_price,
                data_age_seconds=data_age_seconds,
                created_at=created_at,
            )
        )

    def _build_probability_drift(
        self,
        scope: str,
        latest: ProbabilitySnapshot,
        previous: ProbabilitySnapshot | None,
    ) -> ProbabilityDrift:
        if previous is None:
            return ProbabilityDrift(
                scope=scope,
                latest_snapshot=latest,
                previous_snapshot=None,
                fair_probability_delta=None,
                confidence_delta=None,
                source_count_delta=None,
                confidence_component_deltas={},
                source_type_contribution_deltas={},
                drift_summary="No previous snapshot available for comparison.",
            )
        component_keys = set(latest.probability.confidence_components) | set(previous.probability.confidence_components)
        component_deltas = {
            key: round(latest.probability.confidence_components.get(key, 0.0) - previous.probability.confidence_components.get(key, 0.0), 4)
            for key in sorted(component_keys)
        }
        contribution_keys = set(latest.probability.source_type_contributions) | set(previous.probability.source_type_contributions)
        contribution_deltas = {
            key: round(
                latest.probability.source_type_contributions.get(key, 0.0)
                - previous.probability.source_type_contributions.get(key, 0.0),
                4,
            )
            for key in sorted(contribution_keys)
        }
        latest_factors = set(latest.probability.key_factors)
        previous_factors = set(previous.probability.key_factors)
        latest_evidence = {
            f"{item.source_type.value}:{item.source_name}" for item in latest.probability.evidence_records
        }
        previous_evidence = {
            f"{item.source_type.value}:{item.source_name}" for item in previous.probability.evidence_records
        }
        fair_delta = round(latest.probability.fair_probability - previous.probability.fair_probability, 4)
        conf_delta = round(latest.probability.confidence - previous.probability.confidence, 4)
        source_delta = latest.probability.source_count - previous.probability.source_count
        return ProbabilityDrift(
            scope=scope,
            latest_snapshot=latest,
            previous_snapshot=previous,
            fair_probability_delta=fair_delta,
            confidence_delta=conf_delta,
            source_count_delta=source_delta,
            confidence_component_deltas=component_deltas,
            source_type_contribution_deltas=contribution_deltas,
            added_key_factors=sorted(latest_factors - previous_factors),
            removed_key_factors=sorted(previous_factors - latest_factors),
            added_evidence_sources=sorted(latest_evidence - previous_evidence),
            removed_evidence_sources=sorted(previous_evidence - latest_evidence),
            drift_summary=(
                f"fair_probability_delta={fair_delta:+.4f}, "
                f"confidence_delta={conf_delta:+.4f}, "
                f"source_count_delta={source_delta:+d}, "
                f"evidence_added={len(latest_evidence - previous_evidence)}, "
                f"evidence_removed={len(previous_evidence - latest_evidence)}"
            ),
        )
