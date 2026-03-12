from __future__ import annotations

from dataclasses import dataclass

from bot.config.models import Settings
from bot.domain.models import OpportunityDraftAction, OpportunityDraftResult
from bot.services.market_opportunity_scanner import MarketOpportunityScannerService
from bot.services.proposal_lifecycle import ProposalLifecycleService


@dataclass(slots=True)
class OpportunityProposalBridgeService:
    scanner_service: MarketOpportunityScannerService
    proposal_service: ProposalLifecycleService

    def draft_opportunities(
        self,
        settings: Settings,
        min_edge: float | None = None,
        min_liquidity: float | None = None,
        limit: int = 20,
    ) -> OpportunityDraftResult:
        scan_result = self.scanner_service.scan(
            settings,
            min_edge=min_edge,
            min_liquidity=min_liquidity,
            limit=limit,
        )

        created: list[OpportunityDraftAction] = []
        skipped: list[OpportunityDraftAction] = []
        seen_market_ids = {
            proposal.market_id for proposal in self.proposal_service.list_active_proposals()
        }

        for opportunity in scan_result.opportunities:
            if opportunity.market_id in seen_market_ids:
                existing = self.proposal_service.latest_active_proposal_for_market(opportunity.market_id)
                skipped.append(
                    OpportunityDraftAction(
                        market_id=opportunity.market_id,
                        market_title=opportunity.market_title,
                        action="skipped",
                        reason="duplicate_active_proposal",
                        proposal_id=None if existing is None else existing.proposal_id,
                        proposal_status=None if existing is None else existing.status,
                        edge=opportunity.edge,
                    )
                )
                continue

            try:
                snapshot = self.scanner_service.market_data_service.inspect_snapshot(opportunity.market_id, refresh=False)
                probability = self.scanner_service.estimate_probability(snapshot)
                context = self.proposal_service.proposal_engine.create_default_context(
                    snapshot.market,
                    probability,
                    snapshot.orderbook.midpoint,
                )
                context.thesis = [
                    "scanner opportunity detected",
                    f"scanner_edge={opportunity.edge:+.4f}",
                ]
                context.risks = ["scanner-generated draft requires manual operator review"]
                proposal = self.proposal_service.create(settings, context)
            except Exception as exc:
                skipped.append(
                    OpportunityDraftAction(
                        market_id=opportunity.market_id,
                        market_title=opportunity.market_title,
                        action="skipped",
                        reason=str(exc),
                        edge=opportunity.edge,
                    )
                )
                continue

            created.append(
                OpportunityDraftAction(
                    market_id=opportunity.market_id,
                    market_title=opportunity.market_title,
                    action="created",
                    reason="draft_created",
                    proposal_id=proposal.proposal_id,
                    proposal_status=proposal.status,
                    edge=proposal.edge,
                )
            )
            seen_market_ids.add(opportunity.market_id)

        return OpportunityDraftResult(created=created, skipped=skipped)
