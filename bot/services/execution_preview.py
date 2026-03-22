from __future__ import annotations

import logging

from bot.domain.enums import ExecutionPreviewStatus, ProposalStatus
from bot.domain.models import ExecutionPreview, TradeProposal
from bot.integrations.polymarket_gateway import PolymarketGateway, PolymarketGatewayConfigError, PolymarketGatewayOrder
from bot.services.audit_log import AuditLogService
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.utils.ids import new_id
from bot.utils.time import utc_now

logger = logging.getLogger(__name__)


class ExecutionPreviewService:
    """Build explicit non-live execution previews through the optional gateway."""

    def __init__(
        self,
        proposal_service: ProposalLifecycleService,
        audit_log: AuditLogService,
        polymarket_gateway: PolymarketGateway | None = None,
    ) -> None:
        self.proposal_service = proposal_service
        self.audit_log = audit_log
        self.polymarket_gateway = polymarket_gateway

    def preview_proposal(self, proposal_id: str) -> ExecutionPreview:
        return self.build_preview(self.proposal_service.get(proposal_id))

    def build_preview(self, proposal: TradeProposal) -> ExecutionPreview:
        created_at = utc_now()
        preview_id = new_id("preview")
        self.audit_log.log(
            "execution_preview_requested",
            proposal.proposal_id,
            "Execution preview requested",
            {"preview_id": preview_id, "market_id": proposal.market_id, "source": "polymarket_gateway"},
            created_at=created_at,
        )
        warnings: list[str] = []
        validation_errors: list[str] = []
        preview_payload: dict[str, object] = {
            "proposal_id": proposal.proposal_id,
            "market_id": proposal.market_id,
            "side": proposal.side,
            "limit_price": round(proposal.current_limit_price, 4),
            "size_usd": round(proposal.current_size_usd, 2),
            "source": "polymarket_gateway",
            "dry_run": True,
        }
        event_id: str | None = None
        condition_id: str | None = None
        token_id: str | None = None
        quoted_price: float | None = None
        normalized_size_usd: float | None = None
        estimated_shares: float | None = None

        if proposal.status not in {ProposalStatus.PENDING_MANUAL_CONFIRMATION, ProposalStatus.APPROVED}:
            validation_errors.append("proposal is not in a reviewable or approved status")
        if proposal.current_size_usd <= 0:
            validation_errors.append("proposal size must be positive")
        if not 0 < proposal.current_limit_price <= 1:
            validation_errors.append("proposal limit price must be between 0 and 1")
        if proposal.side not in {"yes", "no"}:
            validation_errors.append("proposal side must be yes or no")

        gateway = self.polymarket_gateway
        if gateway is None:
            validation_errors.append("polymarket gateway is not configured")
        elif not gateway.config.enable_polymarket_gateway:
            validation_errors.append("polymarket gateway is disabled")

        if not validation_errors and gateway is not None:
            try:
                metadata = gateway.get_market_metadata(proposal.market_id)
                event_id = metadata.event_id
                condition_id = metadata.condition_id
                if metadata.market.market_id != proposal.market_id:
                    validation_errors.append("gateway market resolution does not match proposal market_id")
                token_id, token_warning, token_error = self._resolve_token(metadata, proposal.side)
                if token_warning is not None:
                    warnings.append(token_warning)
                if token_error is not None:
                    validation_errors.append(token_error)
                quote = gateway.quote_order(
                    PolymarketGatewayOrder(
                        market_id=proposal.market_id,
                        side=proposal.side,
                        size_usd=proposal.current_size_usd,
                        limit_price=proposal.current_limit_price,
                    )
                )
                quoted_price = quote.reference_price
                normalized_size_usd = round(quote.size_usd, 2)
                estimated_shares = quote.estimated_shares
                if abs(quote.reference_price - proposal.current_limit_price) >= 0.02:
                    warnings.append("quoted price differs materially from proposal limit price")
                preview_payload.update(
                    {
                        "event_id": event_id,
                        "condition_id": condition_id,
                        "token_id": token_id,
                        "quoted_price": round(quote.reference_price, 4),
                        "estimated_shares": quote.estimated_shares,
                    }
                )
            except PolymarketGatewayConfigError as exc:
                validation_errors.append(str(exc))
            except Exception as exc:
                validation_errors.append(f"gateway preview failed: {exc.__class__.__name__}")

        preview = ExecutionPreview(
            preview_id=preview_id,
            proposal_id=proposal.proposal_id,
            source="polymarket_gateway",
            dry_run=True,
            market_id=proposal.market_id,
            event_id=event_id,
            condition_id=condition_id,
            token_id=token_id,
            side=proposal.side,
            intended_price=proposal.current_limit_price,
            quoted_price=quoted_price,
            intended_size_usd=proposal.current_size_usd,
            normalized_size_usd=normalized_size_usd,
            estimated_shares=estimated_shares,
            status=self._status_for(warnings, validation_errors),
            warnings=warnings,
            validation_errors=validation_errors,
            preview_payload=preview_payload,
            created_at=created_at,
        )
        self._log_preview_result(preview)
        return preview

    def _resolve_token(self, metadata, side: str) -> tuple[str | None, str | None, str | None]:
        token_id = metadata.outcome_token_ids.get(side)
        if token_id is not None:
            return token_id, None, None
        if metadata.asset_id:
            return metadata.asset_id, f"side-specific token for {side} was not resolved; using gateway asset_id fallback", None
        return None, None, "gateway metadata did not expose a token id"

    def _status_for(self, warnings: list[str], validation_errors: list[str]) -> ExecutionPreviewStatus:
        if validation_errors:
            return ExecutionPreviewStatus.BLOCKED
        if warnings:
            return ExecutionPreviewStatus.READY_WITH_WARNINGS
        return ExecutionPreviewStatus.READY

    def _log_preview_result(self, preview: ExecutionPreview) -> None:
        payload = {
            "preview_id": preview.preview_id,
            "market_id": preview.market_id,
            "token_id": preview.token_id,
            "side": preview.side,
            "intended_price": round(preview.intended_price, 4),
            "quoted_price": None if preview.quoted_price is None else round(preview.quoted_price, 4),
            "intended_size_usd": round(preview.intended_size_usd, 2),
            "normalized_size_usd": None if preview.normalized_size_usd is None else round(preview.normalized_size_usd, 2),
            "estimated_shares": preview.estimated_shares,
            "warnings": preview.warnings,
            "validation_errors": preview.validation_errors,
            "dry_run": preview.dry_run,
        }
        if preview.status == ExecutionPreviewStatus.BLOCKED:
            self.audit_log.log(
                "execution_preview_failed",
                preview.proposal_id,
                "Execution preview blocked",
                payload,
                created_at=preview.created_at,
            )
            logger.warning("execution_preview_failed %s", payload)
            return
        self.audit_log.log(
            "execution_preview_succeeded",
            preview.proposal_id,
            "Execution preview prepared",
            payload,
            created_at=preview.created_at,
        )
        if preview.warnings:
            logger.warning("execution_preview_prepared_with_warnings %s", payload)
        else:
            logger.info("execution_preview_prepared %s", payload)
