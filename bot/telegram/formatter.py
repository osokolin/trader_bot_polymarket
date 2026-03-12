from __future__ import annotations

from bot.domain.enums import OperatorActionEntityType, OperatorActionRequestStatus, OperatorActionRequestType, ProposalStatus
from bot.services.telegram_operator_service import TelegramNotification
from bot.telegram.actions import proposal_callback, request_callback


def unauthorized_message() -> str:
    return "Unauthorized operator."


def help_message() -> str:
    return (
        "Telegram operator inbox\n\n"
        "Commands:\n"
        "/start\n"
        "/help\n"
        "/status\n"
        "/diagnostics\n"
        "/scan\n"
        "/inbox\n"
        "/request <id>\n"
        "/proposals\n"
        "/proposal <id>\n"
        "/approve <id>\n"
        "/reject <id>\n"
        "/cancel <id>\n"
        "/analysis <id>\n"
        "/alerts"
    )


def status_message(status: dict[str, object]) -> str:
    return (
        "Mode: {mode}\n"
        "Profile: {profile}\n"
        "Live execution: {live}\n"
        "Active proposals: {proposals}\n"
        "Open alerts: {alerts}\n"
        "semi_auto strict: {strict}"
    ).format(
        mode=status["mode"],
        profile=status["profile"],
        live="enabled" if status["live_execution_enabled"] else "disabled",
        proposals=status["active_proposals"],
        alerts=status["open_alerts"],
        strict="yes" if status["semi_auto_strict"] else "no",
    )


def diagnostics_message(result) -> str:
    def fmt(label: str, check) -> str:
        state = "OK" if check.ok else "FAIL"
        suffix = "" if check.ok else f" ({check.message})"
        return f"{label}: {state}{suffix}"

    return "\n".join(
        [
            "Polymarket diagnostics",
            fmt("Gamma", result.gamma),
            fmt("CLOB REST", result.clob_rest),
            fmt("WebSocket", result.websocket),
            fmt("Database", result.database),
            f"Overall: {'OK' if result.overall_ok else 'FAIL'}",
        ]
    )


def scan_message(result) -> str:
    if not result.opportunities:
        return "Scanner results\n\nNo opportunities matched the current filters."
    lines = [f"Scanner results ({len(result.opportunities)})"]
    for item in result.opportunities[:5]:
        lines.append(
            f"- {item.market_title}\n"
            f"  market={item.market_id} edge={item.edge:+.4f} fair={item.fair_probability:.4f} "
            f"price={item.market_price:.4f} conf={item.confidence:.2f}"
        )
    return "\n".join(lines)


def proposals_message(proposals) -> str:
    if not proposals:
        return "Proposals\n\nNo active proposals."
    lines = ["Active proposals"]
    for proposal in proposals:
        lines.append(
            f"- {proposal.proposal_id} | {proposal.status.value}\n"
            f"  {proposal.market_title}\n"
            f"  edge={proposal.edge:+.4f} conf={proposal.confidence:.2f}"
        )
    return "\n".join(lines)


def proposal_message(proposal) -> str:
    return (
        f"Proposal {proposal.proposal_id}\n"
        f"Market: {proposal.market_title}\n"
        f"Status: {proposal.status.value}\n"
        f"Edge: {proposal.edge:+.4f}\n"
        f"Confidence: {proposal.confidence:.2f}\n"
        f"Price: {proposal.market_price:.4f}\n"
        f"Fair probability: {proposal.fair_probability:.4f}"
    )


def proposal_action_message(action: str, proposal) -> str:
    labels = {
        "approve": "Proposal approved",
        "reject": "Proposal rejected",
        "cancel": "Proposal cancelled",
    }
    return f"{labels[action]}\nProposal ID: {proposal.proposal_id}"


def proposal_analysis_message(analysis) -> str:
    drift = analysis.decision_review.probability_drift
    latest = analysis.decision_review.probability_snapshot
    previous_probability = "-" if drift.previous_snapshot is None else f"{drift.previous_snapshot.probability.fair_probability:.4f}"
    probability_drift = "-" if drift.fair_probability_delta is None else f"{drift.fair_probability_delta:+.4f}"
    return (
        "Additional Analysis\n\n"
        f"Proposal ID: {analysis.proposal.proposal_id}\n"
        f"Latest probability: {latest.probability.fair_probability:.4f}\n"
        f"Previous probability: {previous_probability}\n"
        f"Drift: {probability_drift}\n"
        f"Confidence: {latest.probability.confidence:.2f}\n"
        f"Scanner rationale: {analysis.scanner_rationale}"
    )


def inbox_message(requests) -> str:
    if not requests:
        return "Decision Inbox\n\nNo open requests."
    lines = ["Decision Inbox"]
    for index, request in enumerate(requests, start=1):
        lines.append(
            f"{index}. {request.request_type.value} | {request.entity_id} | {request.status.value}"
        )
    return "\n".join(lines)


def request_message(view) -> str:
    request = view.request
    if request.request_type == OperatorActionRequestType.PROPOSAL_REVIEW_REQUEST and view.proposal is not None:
        proposal = view.proposal
        return (
            "Proposal Review Request\n\n"
            f"Request ID: {request.request_id}\n"
            f"Proposal ID: {proposal.proposal_id}\n"
            f"Market: {proposal.market_title}\n"
            f"Price: {proposal.market_price:.4f}\n"
            f"Fair probability: {proposal.fair_probability:.4f}\n"
            f"Edge: {proposal.edge:+.4f}\n"
            f"Confidence: {proposal.confidence:.2f}\n"
            f"Status: {request.status.value}"
        )
    if request.request_type == OperatorActionRequestType.ALERT_NOTIFICATION and view.alert is not None:
        return (
            "Alert Notification\n\n"
            f"Request ID: {request.request_id}\n"
            f"Alert ID: {view.alert.alert_id}\n"
            f"Type: {view.alert.alert_type.value}\n"
            f"Summary: {view.alert.summary}\n"
            f"Status: {request.status.value}"
        )
    if request.request_type == OperatorActionRequestType.DIAGNOSTICS_ISSUE:
        detail = request.payload.get("message", "-")
        return (
            "Diagnostics Issue\n\n"
            f"Request ID: {request.request_id}\n"
            f"Check: {request.entity_id}\n"
            f"Summary: {detail}\n"
            f"Status: {request.status.value}"
        )
    return (
        "Decision Request\n\n"
        f"Request ID: {request.request_id}\n"
        f"Type: {request.request_type.value}\n"
        f"Entity: {request.entity_id}\n"
        f"Status: {request.status.value}"
    )


def request_action_message(result) -> str:
    action = result.action
    request = result.request
    labels = {
        "approve": "Request approved",
        "reject": "Request rejected",
        "cancel": "Request cancelled",
        "analysis": "Additional analysis ready",
        "acknowledge": "Alert acknowledged",
        "refresh": "Diagnostics refreshed",
        "details": "Request details",
    }
    return f"{labels.get(action, action)}\nRequest ID: {request.request_id}"


def alerts_message(alerts) -> str:
    if not alerts:
        return "Alerts\n\nNo open alerts."
    lines = ["Open alerts"]
    for alert in alerts:
        lines.append(f"- {alert.alert_type.value} | {alert.summary}")
    return "\n".join(lines)


def command_error_message(exc: Exception) -> str:
    return f"Command failed: {exc}"


def notification_message(notification: TelegramNotification) -> str:
    if notification.kind == "draft_proposal":
        proposal = notification.payload
        return (
            "New Draft Proposal\n\n"
            f"Market: {proposal.market_title}\n"
            f"Edge: {proposal.edge:+.4f}\n"
            f"Confidence: {proposal.confidence:.2f}\n"
            f"Proposal ID: {proposal.proposal_id}\n"
            f"Use /proposal {proposal.proposal_id} to inspect."
        )
    if notification.kind == "alert":
        alert = notification.payload
        return f"Alert\n\n{alert.summary}\nType: {alert.alert_type.value}"
    if notification.kind == "diagnostics_failure":
        return f"Diagnostics failure\n\n{diagnostics_message(notification.payload)}"
    if notification.kind == "inbox_request":
        return (
            "Decision Inbox Request\n\n"
            f"{notification.payload.title}\n"
            f"Request ID: {notification.payload.request_id}\n"
            f"Summary: {notification.payload.summary}\n"
            f"Use /request {notification.payload.request_id} to inspect."
        )
    return "Unknown notification"


def proposal_actions_markup(proposal) -> dict[str, object] | None:
    first_row: list[dict[str, str]] = []
    if proposal.status == ProposalStatus.PENDING_MANUAL_CONFIRMATION:
        first_row.extend(
            [
                {"text": "Approve", "callback_data": proposal_callback("approve", proposal.proposal_id)},
                {"text": "Reject", "callback_data": proposal_callback("reject", proposal.proposal_id)},
            ]
        )
    if proposal.status in {ProposalStatus.PENDING_MANUAL_CONFIRMATION, ProposalStatus.APPROVED}:
        first_row.append({"text": "Cancel", "callback_data": proposal_callback("cancel", proposal.proposal_id)})

    rows: list[list[dict[str, str]]] = []
    if first_row:
        rows.append(first_row)
    rows.append(
        [
            {"text": "More Analysis", "callback_data": proposal_callback("analysis", proposal.proposal_id)},
            {"text": "Details", "callback_data": proposal_callback("details", proposal.proposal_id)},
        ]
    )
    return {"inline_keyboard": rows}


def notification_markup(notification: TelegramNotification) -> dict[str, object] | None:
    if notification.kind == "draft_proposal":
        return proposal_actions_markup(notification.payload)
    if notification.kind == "inbox_request":
        return request_actions_markup(notification.payload)
    return None


def request_actions_markup(request) -> dict[str, object] | None:
    rows: list[list[dict[str, str]]] = []
    if request.request_type == OperatorActionRequestType.PROPOSAL_REVIEW_REQUEST:
        if request.status in OperatorActionRequestStatus.active_states():
            rows.append(
                [
                    {"text": "Approve", "callback_data": request_callback("approve", request.request_id)},
                    {"text": "Reject", "callback_data": request_callback("reject", request.request_id)},
                    {"text": "Cancel", "callback_data": request_callback("cancel", request.request_id)},
                ]
            )
            rows.append(
                [
                    {"text": "More Analysis", "callback_data": request_callback("analysis", request.request_id)},
                    {"text": "Details", "callback_data": request_callback("details", request.request_id)},
                ]
            )
    elif request.request_type == OperatorActionRequestType.ALERT_NOTIFICATION:
        rows.append(
            [
                {"text": "Acknowledge", "callback_data": request_callback("acknowledge", request.request_id)},
                {"text": "Details", "callback_data": request_callback("details", request.request_id)},
            ]
        )
    elif request.request_type == OperatorActionRequestType.DIAGNOSTICS_ISSUE:
        rows.append(
            [
                {"text": "Refresh Summary", "callback_data": request_callback("refresh", request.request_id)},
                {"text": "Details", "callback_data": request_callback("details", request.request_id)},
            ]
        )
    return {"inline_keyboard": rows} if rows else None
