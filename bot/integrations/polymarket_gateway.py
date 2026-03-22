from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bot.adapters.polymarket.clob_client import ClobMarketDataClient, PolymarketOrderBookAdapter
from bot.adapters.polymarket.gamma_client import GammaApiClient, PolymarketMarketMetadataAdapter
from bot.adapters.polymarket.models import GammaMarketSummary
from bot.config.models import PolymarketGatewayConfig
from bot.domain.models import Market, OrderBookSnapshot
from bot.security.trading_signer import TradingSigner
from bot.services.market_catalog import MarketCatalogService


class PolymarketGatewayConfigError(RuntimeError):
    """Raised when the optional gateway is disabled or not safe to use."""


@dataclass(slots=True)
class PolymarketGatewayMarket:
    market_id: str
    title: str
    category: str
    slug: str | None
    event_title: str | None
    active: bool
    closed: bool
    liquidity_usd: float | None
    end_time: datetime | None


@dataclass(slots=True)
class PolymarketGatewayMetadata:
    market: Market
    asset_id: str
    slug: str | None
    event_title: str | None
    gamma_payload: dict[str, object]


@dataclass(slots=True)
class PolymarketGatewayOrderBook:
    market_id: str
    asset_id: str
    snapshot: OrderBookSnapshot
    reference_price: float | None
    pricing_metadata: dict[str, object]


@dataclass(slots=True)
class PolymarketGatewayQuote:
    market_id: str
    side: str
    size_usd: float
    limit_price: float
    reference_price: float
    estimated_shares: float
    dry_run: bool
    message: str


@dataclass(slots=True)
class PolymarketGatewayOrder:
    market_id: str
    side: str
    size_usd: float
    limit_price: float


@dataclass(slots=True)
class PolymarketGatewayOrderReceipt:
    accepted: bool
    dry_run: bool
    order_id: str | None
    message: str


@dataclass(slots=True)
class PolymarketGatewayActionResult:
    success: bool
    dry_run: bool
    message: str


@dataclass(slots=True)
class PolymarketGatewayOpenOrder:
    order_id: str
    market_id: str
    side: str
    size_usd: float
    limit_price: float
    status: str


@dataclass(slots=True)
class PolymarketGatewayPosition:
    market_id: str
    size_usd: float
    average_price: float | None
    side: str | None


class PolymarketGateway:
    """Controlled adapter boundary for Polymarket discovery and execution plumbing.

    The rest of the application should depend on this interface, not on external
    agent/runtime internals. In this milestone live submission stays disabled by
    default; the gateway is primarily a read-only metadata layer with dry-run
    execution skeleton methods.
    """

    def __init__(
        self,
        *,
        config: PolymarketGatewayConfig,
        signer: TradingSigner,
        gamma_client: GammaApiClient,
        clob_client: ClobMarketDataClient,
        market_catalog_service: MarketCatalogService | None = None,
    ) -> None:
        self.config = config
        self.signer = signer
        self.gamma_client = gamma_client
        self.clob_client = clob_client
        self.market_catalog_service = market_catalog_service or MarketCatalogService(gamma_client)
        self.market_metadata_adapter = PolymarketMarketMetadataAdapter(gamma_client)
        self.orderbook_adapter = PolymarketOrderBookAdapter(clob_client)

    def close(self) -> None:
        self.gamma_client.close()
        self.clob_client.close()

    def list_candidate_markets(self, *, limit: int = 20, active: bool = True, closed: bool = False) -> list[PolymarketGatewayMarket]:
        self._require_enabled()
        items = self.market_catalog_service.list_markets(limit=limit, active=active, closed=closed)
        return [self._map_candidate(item) for item in items]

    def get_market_metadata(self, market_id: str) -> PolymarketGatewayMetadata:
        self._require_enabled()
        metadata = self.market_metadata_adapter.get_market_metadata(market_id)
        payload = metadata.raw_payload
        return PolymarketGatewayMetadata(
            market=metadata.market,
            asset_id=metadata.asset_id,
            slug=None if payload.get("slug") is None else str(payload.get("slug")),
            event_title=None if payload.get("event") is None else self._event_title(payload.get("event")),
            gamma_payload=payload,
        )

    def get_orderbook(self, market_id: str) -> PolymarketGatewayOrderBook:
        self._require_enabled()
        metadata = self.market_metadata_adapter.get_market_metadata(market_id)
        orderbook = self.orderbook_adapter.get_orderbook(metadata.asset_id, market_id=market_id)
        return PolymarketGatewayOrderBook(
            market_id=market_id,
            asset_id=metadata.asset_id,
            snapshot=orderbook.snapshot,
            reference_price=orderbook.reference_price,
            pricing_metadata=orderbook.pricing_metadata,
        )

    def quote_order(self, order: PolymarketGatewayOrder) -> PolymarketGatewayQuote:
        self._require_enabled()
        orderbook = self.get_orderbook(order.market_id)
        reference_price = orderbook.reference_price or orderbook.snapshot.midpoint
        effective_price = order.limit_price if order.limit_price > 0 else reference_price
        estimated_shares = round(order.size_usd / effective_price, 4)
        return PolymarketGatewayQuote(
            market_id=order.market_id,
            side=order.side,
            size_usd=order.size_usd,
            limit_price=order.limit_price,
            reference_price=reference_price,
            estimated_shares=estimated_shares,
            dry_run=self.config.dry_run or not self.config.allow_live_order_submission,
            message="Prepared Polymarket gateway quote without changing strategy or review flow",
        )

    def place_order(self, order: PolymarketGatewayOrder) -> PolymarketGatewayOrderReceipt:
        self._require_enabled()
        self.quote_order(order)
        if self.config.dry_run:
            return PolymarketGatewayOrderReceipt(
                accepted=True,
                dry_run=True,
                order_id=None,
                message=f"Dry-run only: would place {order.side} order for {order.market_id}",
            )
        if not self.config.allow_live_order_submission:
            raise PolymarketGatewayConfigError("Live order submission is not enabled for the Polymarket gateway")
        self.signer.validate_for_live_submission()
        raise PolymarketGatewayConfigError(
            "Live Polymarket order submission is intentionally not enabled in this milestone"
        )

    def cancel_order(self, order_id: str) -> PolymarketGatewayActionResult:
        self._require_enabled()
        if self.config.dry_run:
            return PolymarketGatewayActionResult(
                success=True,
                dry_run=True,
                message=f"Dry-run only: would cancel order {order_id}",
            )
        raise PolymarketGatewayConfigError(
            "Order cancellation is intentionally not enabled in this milestone"
        )

    def get_open_orders(self) -> list[PolymarketGatewayOpenOrder]:
        self._require_enabled()
        if self.config.dry_run:
            return []
        if not self.config.allow_live_order_submission:
            return []
        self.signer.validate_for_live_submission()
        raise PolymarketGatewayConfigError(
            "Authenticated order retrieval is intentionally not enabled in this milestone"
        )

    def get_positions(self) -> list[PolymarketGatewayPosition]:
        self._require_enabled()
        if self.config.dry_run:
            return []
        if not self.config.allow_live_order_submission:
            return []
        self.signer.validate_for_live_submission()
        raise PolymarketGatewayConfigError(
            "Authenticated position retrieval is intentionally not enabled in this milestone"
        )

    def _require_enabled(self) -> None:
        if not self.config.enable_polymarket_gateway:
            raise PolymarketGatewayConfigError("Polymarket gateway is disabled by configuration")

    def _map_candidate(self, item: GammaMarketSummary) -> PolymarketGatewayMarket:
        return PolymarketGatewayMarket(
            market_id=item.market_id,
            title=item.question,
            category=item.category,
            slug=item.slug,
            event_title=item.event_title,
            active=item.active,
            closed=item.closed,
            liquidity_usd=item.liquidity_usd,
            end_time=item.end_time,
        )

    def _event_title(self, event_payload: object) -> str | None:
        if isinstance(event_payload, dict):
            title = event_payload.get("title")
            if title is not None:
                return str(title)
        return None
