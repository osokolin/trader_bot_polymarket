from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from bot.domain.models import Market, OrderBookSnapshot


@dataclass(slots=True)
class GammaMarketMetadata:
    market: Market
    asset_id: str
    raw_payload: dict[str, object]


@dataclass(slots=True)
class GammaMarketSummary:
    market_id: str
    question: str
    event_id: str | None
    event_title: str | None
    slug: str | None
    category: str
    active: bool
    closed: bool
    archived: bool
    enable_order_book: bool
    liquidity_usd: float | None = None
    volume_usd: float | None = None
    end_time: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class GammaEventSummary:
    event_id: str
    title: str
    slug: str | None
    active: bool
    closed: bool
    archived: bool
    market_count: int


@dataclass(slots=True)
class ClobOrderBook:
    asset_id: str
    snapshot: OrderBookSnapshot
    reference_price: float | None
    raw_payload: dict[str, object]
    pricing_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ClobMarketUpdate:
    asset_id: str
    best_bid: float
    best_ask: float
    midpoint: float
    spread_pct: float
    timestamp: datetime
    market_id: str | None = None
    reference_price: float | None = None
    sequence_id: str | None = None
    raw_payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class OrderRequest:
    market_id: str
    side: str
    size_usd: float
    limit_price: float
    best_bid: float | None = None
    best_ask: float | None = None
    ttl_ms: int | None = None
    cancel_after_ms: int | None = None
    base_latency_ms: int | None = None


@dataclass(slots=True)
class OrderResult:
    accepted: bool
    order_id: str | None
    message: str


@dataclass(slots=True)
class SimulationResult:
    stage: str
    accepted: bool
    message: str
    order_id: str | None
    reference_price: float
    best_bid: float | None = None
    best_ask: float | None = None
    simulated_price: float | None = None
    slippage_bps: float | None = None
    filled_size_usd: float = 0.0
    fill_timestamp: datetime | None = None
    latency_ms: int | None = None
    completion_reason: str | None = None
    fill_fragments: list["SimulationFillFragment"] = field(default_factory=list)


@dataclass(slots=True)
class SimulationFillFragment:
    event_type: str
    fragment_index: int
    price: float
    size_usd: float
    remaining_size_usd: float
    latency_ms: int
    event_timestamp: datetime
    message: str


@dataclass(slots=True)
class SubmissionOutcome:
    stage: str
    accepted: bool
    message: str
    order_id: str | None = None
    reference_price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    simulated_price: float | None = None
    slippage_bps: float | None = None
    filled_size_usd: float | None = None
    fill_timestamp: datetime | None = None
    latency_ms: int | None = None
    completion_reason: str | None = None
