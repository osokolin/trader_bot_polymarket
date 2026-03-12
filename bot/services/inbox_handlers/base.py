from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from bot.domain.enums import (
    OperatorActionRequestStatus,
    OperatorActionRequestType,
)
from bot.domain.models import OperatorActionRequest, OperatorAlert, TradeProposal
from bot.services.decision_review import DecisionReview
from bot.services.polymarket_diagnostics import DiagnosticCheckResult, PolymarketDiagnosticsResult


class DecisionInboxError(ValueError):
    pass


@dataclass(slots=True)
class DecisionInboxRequestView:
    request: OperatorActionRequest
    proposal: TradeProposal | None = None
    alert: OperatorAlert | None = None
    diagnostics_label: str | None = None
    diagnostics_check: DiagnosticCheckResult | None = None


@dataclass(slots=True)
class InboxHandlerActionOutcome:
    request_status: OperatorActionRequestStatus | None = None
    mark_actioned: bool = False
    update_request: bool = True
    record_action: bool = True
    summary: str | None = None
    payload: dict[str, object] | None = None
    action_payload: dict[str, object] = field(default_factory=dict)
    proposal: TradeProposal | None = None
    alert: OperatorAlert | None = None
    decision_review: DecisionReview | None = None
    diagnostics_result: PolymarketDiagnosticsResult | None = None


class DecisionInboxRequestHandler(ABC):
    request_type: OperatorActionRequestType

    @abstractmethod
    def build_view(self, request: OperatorActionRequest) -> DecisionInboxRequestView:
        raise NotImplementedError

    @abstractmethod
    def apply_action(
        self,
        request: OperatorActionRequest,
        action: str,
        actor: str,
        metadata: dict[str, object],
    ) -> InboxHandlerActionOutcome:
        raise NotImplementedError
