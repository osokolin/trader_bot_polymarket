from __future__ import annotations

from bot.domain.enums import ProposalStatus
from bot.services.telegram_operator_service import TelegramNotification
from bot.telegram.actions import proposal_callback


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
    return None
