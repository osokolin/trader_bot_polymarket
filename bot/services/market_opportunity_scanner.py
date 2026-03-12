from __future__ import annotations

from dataclasses import dataclass

from bot.config.models import Settings
from bot.domain.enums import SourceType
from bot.domain.models import OpportunityCandidate, OpportunityScanResult, ProbabilityEstimate
from bot.services.market_catalog import MarketCatalogService
from bot.services.market_sync import LiveMarketDataService
from bot.utils.math import clamp


@dataclass(slots=True)
class MarketOpportunityScannerService:
    market_catalog_service: MarketCatalogService
    market_data_service: LiveMarketDataService

    def scan(
        self,
        settings: Settings,
        min_edge: float | None = None,
        min_liquidity: float | None = None,
        limit: int = 20,
    ) -> OpportunityScanResult:
        edge_threshold = settings.entry_rules.min_edge_pct if min_edge is None else min_edge
        liquidity_threshold = settings.market_filters.min_liquidity_usd if min_liquidity is None else min_liquidity
        candidate_limit = max(limit * 4, 20)
        try:
            market_summaries = self.market_catalog_service.list_markets(limit=candidate_limit, active=True, closed=False)
        except Exception as exc:
            return OpportunityScanResult(
                opportunities=[],
                scanned_count=0,
                skipped_count=0,
                warning_messages=[f"scan_unavailable: {exc}"],
            )

        opportunities: list[OpportunityCandidate] = []
        warning_messages: list[str] = []
        skipped_count = 0
        scanned_count = 0

        for item in market_summaries:
            if settings.market_filters.allowed_categories and item.category not in settings.market_filters.allowed_categories:
                skipped_count += 1
                continue
            if item.category in settings.market_filters.blocked_categories:
                skipped_count += 1
                continue
            if not item.enable_order_book:
                skipped_count += 1
                continue
            if item.liquidity_usd is not None and item.liquidity_usd < liquidity_threshold:
                skipped_count += 1
                continue
            scanned_count += 1
            try:
                snapshot = self.market_data_service.inspect_snapshot(item.market_id, refresh=False)
            except Exception as exc:
                skipped_count += 1
                warning_messages.append(f"{item.market_id}: {exc}")
                continue

            probability = self.estimate_probability(snapshot)
            edge = round(probability.fair_probability - snapshot.orderbook.midpoint, 4)
            if abs(edge) < edge_threshold:
                continue

            opportunities.append(
                OpportunityCandidate(
                    market_id=snapshot.market_id,
                    market_title=snapshot.market.title,
                    category=snapshot.market.category,
                    market_price=round(snapshot.orderbook.midpoint, 4),
                    fair_probability=probability.fair_probability,
                    edge=edge,
                    confidence=probability.confidence,
                    liquidity_usd=snapshot.market.liquidity_usd,
                    source=snapshot.source,
                )
            )

        opportunities.sort(key=lambda item: (abs(item.edge), item.confidence, item.liquidity_usd or 0.0), reverse=True)
        return OpportunityScanResult(
            opportunities=opportunities[:limit],
            scanned_count=scanned_count,
            skipped_count=skipped_count,
            warning_messages=warning_messages,
        )

    def estimate_probability(self, snapshot) -> ProbabilityEstimate:
        market_price = snapshot.orderbook.midpoint
        reference_price = snapshot.reference_price if snapshot.reference_price is not None else market_price
        fair_probability = clamp(round((market_price + reference_price) / 2, 4), 0.0, 1.0)
        liquidity_component = clamp(snapshot.market.liquidity_usd / 10000, 0.0, 1.0)
        spread_component = clamp(1 - (snapshot.orderbook.spread_pct / 0.03), 0.0, 1.0)
        confidence = round((snapshot.market.rules_confidence + liquidity_component + spread_component) / 3, 4)
        return ProbabilityEstimate(
            market_id=snapshot.market_id,
            fair_probability=fair_probability,
            confidence=confidence,
            model_agreement=1,
            trusted_source_present=False,
            source_types=[SourceType.RESEARCH],
            key_factors=[
                f"midpoint={market_price:.4f}",
                f"reference_price={reference_price:.4f}",
                f"rules_confidence={snapshot.market.rules_confidence:.2f}",
            ],
            source_count=1,
            confidence_components={
                "rules": round(snapshot.market.rules_confidence, 4),
                "liquidity": round(liquidity_component, 4),
                "spread": round(spread_component, 4),
            },
            explanation="Scanner heuristic blends midpoint, reference price, rules confidence, liquidity, and spread.",
            source_inputs=[
                {"type": "research", "reference_price": reference_price, "midpoint": market_price},
            ],
        )
