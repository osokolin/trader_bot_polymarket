from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
