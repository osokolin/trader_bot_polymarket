from __future__ import annotations

from enum import Enum


class BotMode(str, Enum):
    PAPER = "paper"
    MANUAL_ONLY = "manual_only"
    SEMI_AUTO = "semi_auto"
    LIVE_SMALL = "live_small"
    LIVE_FULL = "live_full"


class ProposalStatus(str, Enum):
    DETECTED = "detected"
    SCORED = "scored"
    POLICY_REJECTED = "policy_rejected"
    PENDING_MANUAL_CONFIRMATION = "pending_manual_confirmation"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXIT_PENDING_CONFIRMATION = "exit_pending_confirmation"
    CLOSED = "closed"
    PAUSED_BY_SAFETY = "paused_by_safety"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    PAUSED = "paused"


class IntentStatus(str, Enum):
    CREATED = "created"
    PREPARED = "prepared"
    BLOCKED = "blocked"
    SUPERSEDED = "superseded"
    SUBMISSION_ACCEPTED = "submission_accepted"
    SUBMISSION_REJECTED = "submission_rejected"
    SUBMISSION_DISABLED = "submission_disabled"
    SIMULATED_REJECTED = "simulated_rejected"
    SIMULATED_SUBMITTED = "simulated_submitted"
    SIMULATED_PARTIALLY_FILLED = "simulated_partially_filled"
    SIMULATED_FILLED = "simulated_filled"
    SIMULATED_EXPIRED = "simulated_expired"
    SIMULATED_CANCELLED = "simulated_cancelled"

    @classmethod
    def active_states(cls) -> set["IntentStatus"]:
        return {cls.CREATED, cls.PREPARED}

    @classmethod
    def terminal_states(cls) -> set["IntentStatus"]:
        return {
            cls.BLOCKED,
            cls.SUPERSEDED,
            cls.SUBMISSION_ACCEPTED,
            cls.SUBMISSION_REJECTED,
            cls.SUBMISSION_DISABLED,
            cls.SIMULATED_REJECTED,
            cls.SIMULATED_SUBMITTED,
            cls.SIMULATED_PARTIALLY_FILLED,
            cls.SIMULATED_FILLED,
            cls.SIMULATED_EXPIRED,
            cls.SIMULATED_CANCELLED,
        }


class TradeAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class PolicyRejectionReason(str, Enum):
    MARKET_CATEGORY_BLOCKED = "market_category_blocked"
    MARKET_NOT_WHITELISTED = "market_not_whitelisted"
    MARKET_BLACKLISTED = "market_blacklisted"
    LIQUIDITY_TOO_LOW = "liquidity_too_low"
    SPREAD_TOO_WIDE = "spread_too_wide"
    TIME_TO_RESOLUTION_TOO_SHORT = "time_to_resolution_too_short"
    RULES_UNCLEAR = "rules_unclear"
    ORDERBOOK_REQUIRED = "orderbook_required"
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    EDGE_BELOW_THRESHOLD = "edge_below_threshold"
    MODEL_AGREEMENT_TOO_LOW = "model_agreement_too_low"
    TRUSTED_SOURCE_REQUIRED = "trusted_source_required"
    SOURCE_TYPE_NOT_ALLOWED = "source_type_not_allowed"
    AI_ORDERING_DISABLED = "ai_ordering_disabled"
    MANUAL_APPROVAL_REQUIRED = "manual_approval_required"
    ORDER_TYPE_NOT_ALLOWED = "order_type_not_allowed"
    STALE_DATA = "stale_data"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    TOO_MANY_OPEN_POSITIONS = "too_many_open_positions"
    UNRESOLVED_EXPOSURE_TOO_HIGH = "unresolved_exposure_too_high"
    THEME_EXPOSURE_TOO_HIGH = "theme_exposure_too_high"
    PROPOSAL_SIZE_EXCEEDS_LIMIT = "proposal_size_exceeds_limit"


class SourceType(str, Enum):
    OFFICIAL = "official"
    REGULATOR = "regulator"
    MAJOR_MEDIA = "major_media"
    SOCIAL = "social"
    RESEARCH = "research"


class WatchTargetType(str, Enum):
    MARKET = "market"
    PROPOSAL = "proposal"
    INTENT = "intent"


class AlertType(str, Enum):
    PROPOSAL_TTL_NEARING = "proposal_ttl_nearing"
    APPROVED_PROPOSAL_STALE = "approved_proposal_stale"
    ACTIVE_INTENT_SUPERSEDED = "active_intent_superseded"
    SIMULATED_EXECUTION_RECORDED = "simulated_execution_recorded"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class OperatorActionRequestStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ACTIONED = "actioned"
    EXPIRED = "expired"
    DISMISSED = "dismissed"

    @classmethod
    def active_states(cls) -> set["OperatorActionRequestStatus"]:
        return {cls.OPEN, cls.ACKNOWLEDGED}


class OperatorActionRequestType(str, Enum):
    PROPOSAL_REVIEW_REQUEST = "proposal_review_request"
    ALERT_NOTIFICATION = "alert_notification"
    DIAGNOSTICS_ISSUE = "diagnostics_issue"
    SCANNER_SUMMARY = "scanner_summary"


class OperatorActionEntityType(str, Enum):
    PROPOSAL = "proposal"
    ALERT = "alert"
    DIAGNOSTICS = "diagnostics"
    SCANNER = "scanner"
