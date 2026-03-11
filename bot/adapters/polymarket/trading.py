from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta

from bot.adapters.polymarket.models import OrderRequest, OrderResult, SimulationFillFragment, SimulationResult
from bot.domain.enums import IntentStatus
from bot.utils.time import utc_now


class ExecutionAdapter(ABC):
    supports_live_execution: bool = False

    @abstractmethod
    def prepare_order(self, request: OrderRequest) -> OrderResult:
        ...

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> OrderResult:
        ...

    @abstractmethod
    def simulate_order(self, request: OrderRequest) -> SimulationResult:
        ...


class SemiAutoExecutionAdapter(ExecutionAdapter):
    supports_live_execution = False

    def prepare_order(self, request: OrderRequest) -> OrderResult:
        return OrderResult(
            accepted=True,
            order_id=None,
            message=f"Prepared manual order for {request.market_id}",
        )

    def submit_order(self, request: OrderRequest) -> OrderResult:
        return OrderResult(
            accepted=False,
            order_id=None,
            message="Live order submission is disabled in semi_auto mode",
        )

    def simulate_order(self, request: OrderRequest) -> SimulationResult:
        return PaperExecutionAdapter().simulate_order(request)


class PaperExecutionAdapter(ExecutionAdapter):
    supports_live_execution = False

    def prepare_order(self, request: OrderRequest) -> OrderResult:
        return OrderResult(
            accepted=True,
            order_id=None,
            message=f"Prepared simulated order for {request.market_id}",
        )

    def submit_order(self, request: OrderRequest) -> OrderResult:
        return OrderResult(
            accepted=False,
            order_id=None,
            message="Paper adapter does not perform live submission",
        )

    def simulate_order(self, request: OrderRequest) -> SimulationResult:
        reference_price = request.limit_price
        fill_timestamp = utc_now()
        if request.size_usd <= 0 or not 0 < request.limit_price <= 1:
            return SimulationResult(
                stage=IntentStatus.SIMULATED_REJECTED.value,
                accepted=False,
                message="Simulation rejected invalid order parameters",
                order_id=None,
                reference_price=reference_price,
                best_bid=request.best_bid,
                best_ask=request.best_ask,
                simulated_price=None,
                slippage_bps=None,
                filled_size_usd=0.0,
                fill_timestamp=None,
                latency_ms=None,
                completion_reason="invalid_order_parameters",
            )
        best_bid = request.best_bid if request.best_bid is not None else max(0.0, round(request.limit_price - 0.005, 4))
        best_ask = request.best_ask if request.best_ask is not None else round(request.limit_price, 4)
        reference_price = best_ask if request.side == "yes" else best_bid
        base_latency_ms = request.base_latency_ms or 250
        start = utc_now()
        if request.cancel_after_ms is not None:
            fragments = self._build_fill_fragments(
                request=request,
                start=start,
                base_price=reference_price,
                slippage_bps=6.0,
                fill_sizes=[round(request.size_usd * 0.25, 2)],
                base_latency_ms=base_latency_ms,
                terminal_message="Operator cancelled remaining simulated quantity",
            )
            filled_size = round(sum(item.size_usd for item in fragments), 2)
            stage = IntentStatus.SIMULATED_CANCELLED.value
            message = f"Paper execution simulated cancellation for {request.market_id}"
            completion_reason = "operator_cancelled"
        elif request.ttl_ms is not None or request.size_usd > 100:
            fragments = self._build_fill_fragments(
                request=request,
                start=start,
                base_price=reference_price,
                slippage_bps=8.0,
                fill_sizes=[round(request.size_usd * 0.4, 2)],
                base_latency_ms=base_latency_ms,
                terminal_message="Simulated order expired before the remainder filled",
            )
            filled_size = round(sum(item.size_usd for item in fragments), 2)
            stage = IntentStatus.SIMULATED_EXPIRED.value
            message = f"Paper execution simulated expiry for {request.market_id}"
            completion_reason = "ttl_expired"
        elif request.size_usd <= 50:
            fragments = self._build_fill_fragments(
                request=request,
                start=start,
                base_price=reference_price,
                slippage_bps=4.0,
                fill_sizes=[round(request.size_usd, 2)],
                base_latency_ms=base_latency_ms,
                terminal_message="Simulated full fill completed immediately",
            )
            filled_size = request.size_usd
            stage = IntentStatus.SIMULATED_FILLED.value
            message = f"Paper execution simulated full fill for {request.market_id}"
            completion_reason = "fully_filled"
        else:
            first_fill = round(request.size_usd * 0.6, 2)
            second_fill = round(request.size_usd - first_fill, 2)
            fragments = self._build_fill_fragments(
                request=request,
                start=start,
                base_price=reference_price,
                slippage_bps=6.0,
                fill_sizes=[first_fill, second_fill],
                base_latency_ms=base_latency_ms,
                terminal_message="Simulated fill completed across multiple fragments",
            )
            filled_size = round(sum(item.size_usd for item in fragments), 2)
            stage = IntentStatus.SIMULATED_FILLED.value
            message = f"Paper execution simulated partial then complete fill for {request.market_id}"
            completion_reason = "completed_after_partial_fill"
        simulated_price = None if not fragments else round(
            sum(item.price * item.size_usd for item in fragments) / filled_size,
            4,
        )
        slippage_bps = None if simulated_price is None or reference_price == 0 else round(
            ((simulated_price - reference_price) / reference_price) * 10000,
            2,
        )
        return SimulationResult(
            stage=stage,
            accepted=True,
            message=message,
            order_id=f"paper_{request.market_id}",
            reference_price=reference_price,
            best_bid=best_bid,
            best_ask=best_ask,
            simulated_price=simulated_price,
            slippage_bps=slippage_bps,
            filled_size_usd=filled_size,
            fill_timestamp=fragments[-1].event_timestamp if fragments else fill_timestamp,
            latency_ms=0 if not fragments else fragments[-1].latency_ms,
            completion_reason=completion_reason,
            fill_fragments=fragments,
        )

    def _build_fill_fragments(
        self,
        request: OrderRequest,
        start,
        base_price: float,
        slippage_bps: float,
        fill_sizes: list[float],
        base_latency_ms: int,
        terminal_message: str,
    ) -> list[SimulationFillFragment]:
        fragments: list[SimulationFillFragment] = []
        remaining = round(request.size_usd, 2)
        direction = 1 if request.side == "yes" else -1
        for index, fill_size in enumerate(fill_sizes, start=1):
            if fill_size <= 0:
                continue
            remaining = round(max(0.0, remaining - fill_size), 2)
            latency_ms = base_latency_ms * index
            price = min(1.0, max(0.0, round(base_price * (1 + direction * slippage_bps / 10000), 4)))
            fragments.append(
                SimulationFillFragment(
                    event_type="fill",
                    fragment_index=index,
                    price=price,
                    size_usd=fill_size,
                    remaining_size_usd=remaining,
                    latency_ms=latency_ms,
                    event_timestamp=start + timedelta(milliseconds=latency_ms),
                    message=terminal_message if remaining == 0 else f"Simulated fill fragment {index}",
                )
            )
        return fragments
