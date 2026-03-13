from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re

from bot.adapters.polymarket.models import GammaMarketSummary
from bot.config.models import MarketOpportunityAlertsConfig, Settings
from bot.domain.enums import AlertSeverity, AlertType
from bot.domain.models import OperatorAlert
from bot.services.market_catalog import MarketCatalogService
from bot.services.market_research import MarketResearchService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.utils.time import utc_now

SPORTS_CONTEXT_TERMS = (
    "fifa",
    "world cup",
    "qualify",
    "qualifying",
    "match",
    "tournament",
    "champions league",
    "premier league",
    "nba",
    "nfl",
    "mlb",
    "nhl",
    "uefa",
    "f1",
    "formula 1",
)


@dataclass(slots=True)
class MarketOpportunityAlertScanResult:
    created_alerts: list[OperatorAlert]
    scanned_count: int
    relevant_count: int
    warning_messages: list[str]


@dataclass(slots=True)
class MarketOpportunityAlertService:
    market_catalog_service: MarketCatalogService
    notifications_service: OperatorNotificationsService
    market_research_service: MarketResearchService

    def scan(
        self,
        settings: Settings,
        *,
        limit: int = 200,
    ) -> MarketOpportunityAlertScanResult:
        try:
            markets = self.market_catalog_service.list_markets(limit=limit, active=True, closed=False)
        except Exception as exc:
            return MarketOpportunityAlertScanResult(
                created_alerts=[],
                scanned_count=0,
                relevant_count=0,
                warning_messages=[f"scan_unavailable: {exc}"],
            )

        rules = settings.market_opportunity_alerts
        created_alerts: list[OperatorAlert] = []
        scanned_count = 0
        relevant_count = 0

        for market in markets:
            scanned_count += 1
            relevance_reasons = self._relevance_reasons(market, rules)
            if not relevance_reasons:
                continue
            relevant_count += 1

            if self._is_enabled(rules, AlertType.NEW_RELEVANT_MARKET):
                alert = self.notifications_service.create_market_opportunity_alert(
                        alert_type=AlertType.NEW_RELEVANT_MARKET,
                        market_id=market.market_id,
                        severity=AlertSeverity.INFO,
                        summary=f"New relevant market: {market.question}",
                        payload=self._payload(
                            market,
                            why=f"relevance_match={', '.join(relevance_reasons)}",
                        ),
                    )
                if alert is not None:
                    created_alerts.append(alert)

            if (
                self._is_enabled(rules, AlertType.HIGH_LIQUIDITY_MARKET)
                and market.liquidity_usd is not None
                and market.liquidity_usd >= rules.liquidity_threshold
            ):
                alert = self.notifications_service.create_market_opportunity_alert(
                        alert_type=AlertType.HIGH_LIQUIDITY_MARKET,
                        market_id=market.market_id,
                        severity=AlertSeverity.WARNING,
                        summary=f"High-liquidity relevant market: {market.question}",
                        payload=self._payload(
                            market,
                            why=f"liquidity_usd={market.liquidity_usd:,.0f} >= {rules.liquidity_threshold:,.0f}",
                        ),
                    )
                if alert is not None:
                    created_alerts.append(alert)

            if self._is_enabled(rules, AlertType.RESOLVING_SOON_MARKET) and self._is_resolving_soon(market, rules):
                alert = self.notifications_service.create_market_opportunity_alert(
                        alert_type=AlertType.RESOLVING_SOON_MARKET,
                        market_id=market.market_id,
                        severity=AlertSeverity.WARNING,
                        summary=f"Relevant market resolving soon: {market.question}",
                        payload=self._payload(
                            market,
                            why=f"resolves_within_days={rules.resolving_soon_days}",
                        ),
                    )
                if alert is not None:
                    created_alerts.append(alert)

            if self._is_enabled(rules, AlertType.POTENTIAL_CONTEXT_MARKET):
                proposal_context = self.market_research_service.get_market_proposal_context(market.market_id)
                research_context = self.market_research_service.get_market_research_context(market.market_id)
                if (
                    research_context.latest_probability_snapshot is not None
                    or proposal_context.proposal_count > 0
                    or research_context.latest_decision_review is not None
                    or research_context.latest_execution_evaluation is not None
                    or research_context.latest_outcome_analysis is not None
                    or research_context.latest_learning_analysis is not None
                ):
                    context_reasons: list[str] = []
                    if research_context.latest_probability_snapshot is not None:
                        context_reasons.append("research")
                    if proposal_context.proposal_count > 0:
                        context_reasons.append(f"proposal_count={proposal_context.proposal_count}")
                    if research_context.latest_decision_review is not None:
                        context_reasons.append("review")
                    if (
                        research_context.latest_execution_evaluation is not None
                        or research_context.latest_outcome_analysis is not None
                        or research_context.latest_learning_analysis is not None
                    ):
                        context_reasons.append("analysis")
                    alert = self.notifications_service.create_market_opportunity_alert(
                            alert_type=AlertType.POTENTIAL_CONTEXT_MARKET,
                            market_id=market.market_id,
                            severity=AlertSeverity.INFO,
                            summary=f"Relevant market already has system context: {market.question}",
                            payload=self._payload(
                                market,
                                why=f"context={', '.join(context_reasons)}",
                            ),
                        )
                    if alert is not None:
                        created_alerts.append(alert)

        unique_created_alerts: list[OperatorAlert] = []
        seen_ids: set[str] = set()
        for alert in created_alerts:
            if alert.alert_id in seen_ids:
                continue
            seen_ids.add(alert.alert_id)
            unique_created_alerts.append(alert)
        return MarketOpportunityAlertScanResult(
            created_alerts=unique_created_alerts,
            scanned_count=scanned_count,
            relevant_count=relevant_count,
            warning_messages=[],
        )

    def _relevance_reasons(
        self,
        market: GammaMarketSummary,
        rules: MarketOpportunityAlertsConfig,
    ) -> list[str]:
        reasons: list[str] = []
        normalized_categories = {item.strip().lower() for item in rules.tracked_categories}
        market_category = market.category.strip().lower()
        if market_category in normalized_categories:
            reasons.append(f"category={market.category}")

        keyword_matches = self._keyword_matches(market, rules.tracked_keywords)
        if keyword_matches and self._is_sports_like_context(market):
            return reasons
        reasons.extend(f"keyword={keyword}" for keyword in keyword_matches)
        return reasons

    def _keyword_matches(self, market: GammaMarketSummary, tracked_keywords: list[str]) -> list[str]:
        haystack = " ".join(
            part for part in [market.question, market.event_title or "", market.slug or ""] if part
        ).lower()
        matches: list[str] = []
        for keyword in tracked_keywords:
            normalized = keyword.strip().lower()
            if normalized and normalized in haystack:
                matches.append(normalized)
        return matches

    def _is_sports_like_context(self, market: GammaMarketSummary) -> bool:
        haystack = " ".join(
            part
            for part in [
                market.category,
                market.question,
                market.event_title or "",
                market.slug or "",
            ]
            if part
        ).lower()
        normalized_haystack = re.sub(r"[^a-z0-9]+", " ", haystack)
        for term in SPORTS_CONTEXT_TERMS:
            normalized_term = re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()
            if not normalized_term:
                continue
            if re.search(rf"\b{re.escape(normalized_term)}\b", normalized_haystack):
                return True
        return False

    def _is_resolving_soon(self, market: GammaMarketSummary, rules: MarketOpportunityAlertsConfig) -> bool:
        if market.end_time is None or market.closed:
            return False
        return market.end_time <= utc_now() + timedelta(days=rules.resolving_soon_days)

    def _is_enabled(self, rules: MarketOpportunityAlertsConfig, alert_type: AlertType) -> bool:
        return alert_type.value in {item.strip().lower() for item in rules.enabled_alert_types}

    def _payload(self, market: GammaMarketSummary, *, why: str) -> dict[str, object]:
        return {
            "market_title": market.question,
            "category": market.category,
            "liquidity_usd": market.liquidity_usd,
            "resolution_time": None if market.end_time is None else market.end_time.isoformat(),
            "slug": market.slug,
            "why": why,
        }
