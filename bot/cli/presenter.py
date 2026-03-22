from __future__ import annotations

import json
from collections import Counter

from bot.domain.enums import ExecutionPreviewStatus, IntentStatus, ProposalStatus


PROPOSAL_STATUS_HELP = {
    ProposalStatus.PENDING_MANUAL_CONFIRMATION: "Awaiting manual operator decision before any execution step.",
    ProposalStatus.APPROVED: "Passed fresh revalidation and is eligible for manual execution intent creation.",
    ProposalStatus.POLICY_REJECTED: "Rejected by policy or fresh revalidation inputs; manual execution must not continue.",
    ProposalStatus.CANCELLED: "No longer actionable because it was manually rejected or expired by TTL.",
    ProposalStatus.PAUSED_BY_SAFETY: "Trading paused by a safety control and requires operator investigation.",
    ProposalStatus.FILLED: "Execution completed and the proposal has become an open or resolved position.",
    ProposalStatus.CLOSED: "Trade lifecycle finished and no further action is expected.",
}

INTENT_STATUS_HELP = {
    IntentStatus.CREATED: "Intent exists but has not been prepared for operator submission yet.",
    IntentStatus.PREPARED: "Intent is staged for manual submission; no live order has been sent.",
    IntentStatus.BLOCKED: "Preparation failed or was blocked before a submission step could proceed.",
    IntentStatus.SUPERSEDED: "A newer intent replaced this one; it must not be submitted.",
    IntentStatus.SUBMISSION_ACCEPTED: "A downstream adapter accepted the submission request.",
    IntentStatus.SUBMISSION_REJECTED: "A downstream adapter rejected the submission request.",
    IntentStatus.SUBMISSION_DISABLED: "Submission path is disabled by the semi_auto execution boundary.",
    IntentStatus.SIMULATED_REJECTED: "Paper execution rejected the order parameters during operator simulation.",
    IntentStatus.SIMULATED_SUBMITTED: "Paper execution simulated a resting order with no fill yet.",
    IntentStatus.SIMULATED_PARTIALLY_FILLED: "Paper execution simulated a partial fill.",
    IntentStatus.SIMULATED_FILLED: "Paper execution simulated a full fill.",
    IntentStatus.SIMULATED_EXPIRED: "Paper execution simulated a partial or resting order that expired before completion.",
    IntentStatus.SIMULATED_CANCELLED: "Paper execution simulated an operator cancellation before the order fully filled.",
}

EXECUTION_PREVIEW_STATUS_HELP = {
    ExecutionPreviewStatus.READY: "Gateway preview reconciled proposal and market metadata without warnings.",
    ExecutionPreviewStatus.READY_WITH_WARNINGS: "Gateway preview succeeded, but reconciliation produced warnings worth operator review.",
    ExecutionPreviewStatus.BLOCKED: "Gateway preview could not prepare a safe non-live artifact.",
}


def sort_items(items: list, sort_key: str):
    if sort_key == "updated_asc":
        return sorted(items, key=lambda item: item.updated_at)
    if sort_key == "created_desc":
        return sorted(items, key=lambda item: item.created_at, reverse=True)
    if sort_key == "created_asc":
        return sorted(items, key=lambda item: item.created_at)
    if sort_key == "status":
        return sorted(items, key=lambda item: (item.status.value, item.updated_at), reverse=True)
    return sorted(items, key=lambda item: item.updated_at, reverse=True)


def slice_items(items: list, limit: int, offset: int):
    return items[offset : offset + limit]


def status_summary(items: list) -> str:
    counts = Counter(item.status.value for item in items)
    if not counts:
        return "none"
    return ", ".join(f"{status}={counts[status]}" for status in sorted(counts))


def proposal_status_help(proposal) -> str:
    return PROPOSAL_STATUS_HELP.get(proposal.status, "Status has no dedicated operator help text yet.")


def intent_status_help(intent) -> str:
    return INTENT_STATUS_HELP.get(intent.status, "Status has no dedicated operator help text yet.")


def execution_preview_status_help(preview) -> str:
    return EXECUTION_PREVIEW_STATUS_HELP.get(preview.status, "Preview status has no dedicated operator help text yet.")


def format_policy_reasons(proposal) -> str:
    return ",".join(reason.value for reason in proposal.policy_decision.reasons) or "-"


def format_policy_details(proposal) -> str:
    if not proposal.policy_decision.details:
        return "-"
    return json.dumps(proposal.policy_decision.details, sort_keys=True)


def kv_lines(items: list[tuple[str, object]]) -> list[str]:
    return [f"{label}: {value}" for label, value in items]


def proposal_summary_line(proposal) -> str:
    return (
        f"{proposal.updated_at.isoformat()} | {proposal.proposal_id} | {proposal.status.value} | "
        f"edge={proposal.edge:.4f} | conf={proposal.confidence:.2f} | size={proposal.current_size_usd:.2f} | "
        f"price={proposal.market_price:.4f} | limit={proposal.current_limit_price:.4f} | "
        f"policy={format_policy_reasons(proposal)} | title={proposal.market_title}"
    )


def proposal_detail_lines(proposal) -> list[str]:
    return kv_lines(
        [
            ("proposal_id", proposal.proposal_id),
            ("market_id", proposal.market_id),
            ("title", proposal.market_title),
            ("status", proposal.status.value),
            ("status_help", proposal_status_help(proposal)),
            ("created_at", proposal.created_at.isoformat()),
            ("updated_at", proposal.updated_at.isoformat()),
            ("expires_at", proposal.expires_at.isoformat()),
            ("market_price", f"{proposal.market_price:.4f}"),
            ("fair_probability", f"{proposal.fair_probability:.4f}"),
            ("edge", f"{proposal.edge:.4f}"),
            ("confidence", f"{proposal.confidence:.2f}"),
            ("model_agreement", proposal.model_agreement),
            ("trusted_source_present", proposal.trusted_source_present),
            ("source_types", ",".join(item.value for item in proposal.source_types) or "-"),
            ("size_usd", f"{proposal.current_size_usd:.2f}"),
            ("recommended_size_usd", f"{proposal.recommended_size_usd:.2f}"),
            ("max_allowed_size_usd", f"{proposal.max_allowed_size_usd:.2f}"),
            ("limit_price", f"{proposal.current_limit_price:.4f}"),
            ("suggested_limit_price", f"{proposal.suggested_limit_price:.4f}"),
            ("policy_allowed", proposal.policy_decision.allowed),
            ("policy_reasons", format_policy_reasons(proposal)),
            ("policy_details", format_policy_details(proposal)),
            ("thesis_points", len(proposal.thesis)),
            ("risk_points", len(proposal.risks)),
        ]
    )


def intent_summary_line(intent) -> str:
    return (
        f"{intent.updated_at.isoformat()} | {intent.intent_id} | {intent.status.value} | "
        f"proposal={intent.proposal_id} | market={intent.market_id} | side={intent.side} | "
        f"size={intent.size_usd:.2f} | limit={intent.limit_price:.4f} | reason={intent.reason}"
    )


def intent_detail_lines(intent) -> list[str]:
    return kv_lines(
        [
            ("intent_id", intent.intent_id),
            ("proposal_id", intent.proposal_id),
            ("market_id", intent.market_id),
            ("status", intent.status.value),
            ("status_help", intent_status_help(intent)),
            ("created_at", intent.created_at.isoformat()),
            ("updated_at", intent.updated_at.isoformat()),
            ("side", intent.side),
            ("size_usd", f"{intent.size_usd:.2f}"),
            ("limit_price", f"{intent.limit_price:.4f}"),
            ("reason", intent.reason),
            ("superseded_by", intent.superseded_by_intent_id or "-"),
        ]
    )


def execution_history_lines(executions) -> list[str]:
    lines = [f"simulated_execution_count: {len(executions)}"]
    for execution in executions:
        fill_timestamp = execution.fill_timestamp.isoformat() if execution.fill_timestamp else "-"
        simulated_price = "-" if execution.simulated_price is None else f"{execution.simulated_price:.4f}"
        slippage_bps = "-" if execution.slippage_bps is None else f"{execution.slippage_bps:.2f}"
        best_bid = "-" if execution.best_bid is None else f"{execution.best_bid:.4f}"
        best_ask = "-" if execution.best_ask is None else f"{execution.best_ask:.4f}"
        lines.append(
            f"{execution.created_at.isoformat()} | simulated_execution | execution_id={execution.execution_id} | "
            f"status={execution.status.value} | accepted={execution.accepted} | order_id={execution.order_id or '-'} | "
            f"reference_price={execution.reference_price:.4f} | best_bid={best_bid} | best_ask={best_ask} | "
            f"simulated_price={simulated_price} | "
            f"slippage_bps={slippage_bps} | filled_size_usd={execution.filled_size_usd:.2f} | "
            f"fill_timestamp={fill_timestamp} | latency_ms={execution.latency_ms or '-'} | "
            f"completion_reason={execution.completion_reason or '-'} | message={execution.message}"
        )
    return lines


def execution_timeline_lines(events) -> list[str]:
    lines = [f"simulated_fill_event_count: {len(events)}"]
    for event in events:
        lines.append(
            f"{event.event_timestamp.isoformat()} | simulated_fill_event | execution_id={event.execution_id} | "
            f"fragment={event.fragment_index} | type={event.event_type} | price={event.price:.4f} | "
            f"size_usd={event.size_usd:.2f} | remaining_size_usd={event.remaining_size_usd:.2f} | "
            f"latency_ms={event.latency_ms} | message={event.message}"
        )
    return lines


def execution_evaluation_lines(evaluation) -> list[str]:
    realized_price = "-" if evaluation.realized_price is None else f"{evaluation.realized_price:.4f}"
    price_delta = "-" if evaluation.price_delta is None else f"{evaluation.price_delta:+.4f}"
    latency_delta = "-" if evaluation.latency_delta_ms is None else f"{evaluation.latency_delta_ms:+d}"
    return kv_lines(
        [
            ("execution_evaluation_id", evaluation.evaluation_id),
            ("proposal_id", evaluation.proposal_id or "-"),
            ("intent_id", evaluation.intent_id),
            ("execution_id", evaluation.execution_id),
            ("verdict", evaluation.verdict),
            ("intended_price", f"{evaluation.intended_price:.4f}"),
            ("realized_price", realized_price),
            ("price_delta", price_delta),
            ("expected_size_usd", f"{evaluation.expected_size_usd:.2f}"),
            ("filled_size_usd", f"{evaluation.filled_size_usd:.2f}"),
            ("size_fill_ratio", f"{evaluation.size_fill_ratio:.4f}"),
            ("expected_latency_ms", evaluation.expected_latency_ms),
            ("realized_latency_ms", evaluation.realized_latency_ms if evaluation.realized_latency_ms is not None else "-"),
            ("latency_delta_ms", latency_delta),
            ("intended_completion", evaluation.intended_completion),
            ("actual_completion_reason", evaluation.actual_completion_reason),
            ("timeline_event_count", evaluation.timeline_event_count),
            ("summary", evaluation.summary),
            ("created_at", evaluation.created_at.isoformat()),
        ]
    )


def execution_preview_lines(preview) -> list[str]:
    return kv_lines(
        [
            ("preview_id", preview.preview_id),
            ("proposal_id", preview.proposal_id),
            ("source", preview.source),
            ("dry_run", preview.dry_run),
            ("status", preview.status.value),
            ("status_help", execution_preview_status_help(preview)),
            ("market_id", preview.market_id),
            ("event_id", preview.event_id or "-"),
            ("condition_id", preview.condition_id or "-"),
            ("token_id", preview.token_id or "-"),
            ("side", preview.side),
            ("intended_price", f"{preview.intended_price:.4f}"),
            ("quoted_price", "-" if preview.quoted_price is None else f"{preview.quoted_price:.4f}"),
            ("intended_size_usd", f"{preview.intended_size_usd:.2f}"),
            ("normalized_size_usd", "-" if preview.normalized_size_usd is None else f"{preview.normalized_size_usd:.2f}"),
            ("estimated_shares", "-" if preview.estimated_shares is None else f"{preview.estimated_shares:.4f}"),
            ("warning_count", len(preview.warnings)),
            ("validation_error_count", len(preview.validation_errors)),
            ("warnings", json.dumps(preview.warnings, ensure_ascii=True)),
            ("validation_errors", json.dumps(preview.validation_errors, ensure_ascii=True)),
            ("preview_payload", json.dumps(preview.preview_payload, sort_keys=True)),
            ("created_at", preview.created_at.isoformat()),
        ]
    )


def outcome_analysis_lines(snapshot) -> list[str]:
    lines = [
        f"analysis_scope: {snapshot.scope}",
        f"group_by: {snapshot.group_by}",
        f"since_hours: {'-' if snapshot.since_hours is None else snapshot.since_hours}",
        f"analysis_summary: {snapshot.summary}",
        f"group_count: {len(snapshot.groups)}",
    ]
    for group in snapshot.groups:
        lines.append(
            f"group={group.group_value} | reviews={group.review_count} | evaluations={group.evaluation_count} | "
            f"avg_fair_delta={'-' if group.average_fair_probability_delta is None else f'{group.average_fair_probability_delta:+.4f}'} | "
            f"avg_conf_delta={'-' if group.average_confidence_delta is None else f'{group.average_confidence_delta:+.4f}'} | "
            f"confidence_held={group.confidence_held_count} | confidence_degraded={group.confidence_degraded_count} | "
            f"prob_in_favor={group.probability_in_favor_count} | prob_against={group.probability_against_count} | "
            f"exec_favorable={group.execution_favorable_count} | exec_unfavorable={group.execution_unfavorable_count} | "
            f"verdicts={json.dumps(group.verdict_counts, sort_keys=True)}"
        )
    return lines


def latest_execution_lines(execution) -> list[str]:
    if execution is None:
        return ["no_simulated_execution"]
    return execution_history_lines([execution])


def simulation_summary_lines(summary) -> list[str]:
    avg_slippage = "-" if summary.average_slippage_bps is None else f"{summary.average_slippage_bps:.2f}"
    latest_fill = "-" if summary.latest_fill_timestamp is None else summary.latest_fill_timestamp.isoformat()
    return kv_lines(
        [
            ("simulation_scope", summary.scope),
            ("execution_count", summary.execution_count),
            ("accepted_count", summary.accepted_count),
            ("filled_count", summary.filled_count),
            ("partial_fill_count", summary.partial_fill_count),
            ("resting_count", summary.resting_count),
            ("rejected_count", summary.rejected_count),
            ("total_filled_size_usd", f"{summary.total_filled_size_usd:.2f}"),
            ("average_slippage_bps", avg_slippage),
            ("latest_fill_timestamp", latest_fill),
        ]
    )


def analytics_summary_lines(summary) -> list[str]:
    avg_slippage = "-" if summary.average_simulated_slippage_bps is None else f"{summary.average_simulated_slippage_bps:.2f}"
    return kv_lines(
        [
            ("analytics_scope", summary.scope),
            ("since_hours", summary.since_hours if summary.since_hours is not None else "-"),
            ("active_proposal_count", summary.active_proposal_count),
            ("approved_proposal_count", summary.approved_proposal_count),
            ("active_intent_count", summary.active_intent_count),
            ("terminal_intent_count", summary.terminal_intent_count),
            ("simulated_execution_count", summary.simulated_execution_count),
            ("total_simulated_filled_size_usd", f"{summary.total_simulated_filled_size_usd:.2f}"),
            ("average_simulated_slippage_bps", avg_slippage),
        ]
    )


def watchlist_lines(entries) -> list[str]:
    lines = [f"watchlist_count: {len(entries)}"]
    for entry in entries:
        lines.append(
            f"{entry.created_at.isoformat()} | watch | type={entry.target_type.value} | "
            f"id={entry.target_id} | label={entry.label or '-'}"
        )
    return lines


def market_data_lines(snapshot) -> list[str]:
    return kv_lines(
        [
            ("snapshot_id", snapshot.snapshot_id),
            ("market_id", snapshot.market_id),
            ("asset_id", snapshot.asset_id),
            ("source", snapshot.source),
            ("fetched_at", snapshot.fetched_at.isoformat()),
            ("data_age_seconds", snapshot.data_age_seconds),
            ("title", snapshot.market.title),
            ("event_id", snapshot.market.event_id or "-"),
            ("active", snapshot.market.active),
            ("closed", snapshot.market.closed),
            ("archived", snapshot.market.archived),
            ("best_bid", f"{snapshot.orderbook.best_bid:.4f}"),
            ("best_ask", f"{snapshot.orderbook.best_ask:.4f}"),
            ("midpoint", f"{snapshot.orderbook.midpoint:.4f}"),
            ("spread_pct", f"{snapshot.orderbook.spread_pct:.6f}"),
            ("orderbook_timestamp", snapshot.orderbook.timestamp.isoformat()),
            ("observed_at", snapshot.observed_at.isoformat()),
            ("stale", snapshot.stale),
            ("reference_price", "-" if snapshot.reference_price is None else f"{snapshot.reference_price:.4f}"),
            ("pricing_status", snapshot.pricing_metadata.get("price_status", "-")),
            ("websocket_payload_keys", ",".join(sorted(snapshot.websocket_payload.keys())) or "-"),
        ]
    )


def market_catalog_lines(items) -> list[str]:
    lines = [f"market_count: {len(items)}"]
    for item in items:
        liquidity = "-" if item.liquidity_usd is None else f"{item.liquidity_usd:.2f}"
        volume = "-" if item.volume_usd is None else f"{item.volume_usd:.2f}"
        lines.append(
            f"market_id={item.market_id} | question={item.question} | event_id={item.event_id or '-'} | "
            f"category={item.category} | active={item.active} | closed={item.closed} | "
            f"orderbook={item.enable_order_book} | liquidity_usd={liquidity} | volume_usd={volume} | slug={item.slug or '-'}"
        )
    return lines


def market_opportunity_lines(result) -> list[str]:
    lines = [
        "Market opportunity scan",
        f"scanned_count: {result.scanned_count}",
        f"skipped_count: {result.skipped_count}",
        f"opportunity_count: {len(result.opportunities)}",
    ]
    for warning in result.warning_messages:
        lines.append(f"warning: {warning}")
    for item in result.opportunities:
        liquidity = "-" if item.liquidity_usd is None else f"{item.liquidity_usd:.2f}"
        lines.append(
            f"market_id={item.market_id} | title={item.market_title} | category={item.category} | "
            f"market_price={item.market_price:.4f} | fair_probability={item.fair_probability:.4f} | "
            f"edge={item.edge:+.4f} | confidence={item.confidence:.4f} | liquidity_usd={liquidity} | "
            f"source={item.source}"
        )
    return lines


def opportunity_draft_lines(result) -> list[str]:
    lines = [
        "Opportunity proposal bridge",
        f"created_count: {len(result.created)}",
        f"skipped_count: {len(result.skipped)}",
    ]
    for item in result.created:
        lines.append(
            f"action=created | market_id={item.market_id} | title={item.market_title} | "
            f"proposal_id={item.proposal_id or '-'} | status={item.proposal_status.value if item.proposal_status else '-'} | "
            f"edge={'-' if item.edge is None else f'{item.edge:+.4f}'} | reason={item.reason}"
        )
    for item in result.skipped:
        lines.append(
            f"action=skipped | market_id={item.market_id} | title={item.market_title} | "
            f"proposal_id={item.proposal_id or '-'} | status={item.proposal_status.value if item.proposal_status else '-'} | "
            f"edge={'-' if item.edge is None else f'{item.edge:+.4f}'} | reason={item.reason}"
        )
    return lines


def event_catalog_lines(items) -> list[str]:
    lines = [f"event_count: {len(items)}"]
    for item in items:
        lines.append(
            f"event_id={item.event_id} | title={item.title} | active={item.active} | "
            f"closed={item.closed} | archived={item.archived} | markets={item.market_count} | slug={item.slug or '-'}"
        )
    return lines


def polymarket_diagnostics_lines(result) -> list[str]:
    def _fmt(label: str, check) -> str:
        status = "OK" if check.ok else "FAIL"
        suffix = "" if check.ok else f" ({check.message})"
        if check.ok and check.message:
            suffix = f" ({check.message})"
        return f"{label:<20} {status}{suffix}"

    return [
        "Polymarket diagnostics",
        "",
        _fmt("Gamma API ..........", result.gamma),
        _fmt("CLOB REST ..........", result.clob_rest),
        _fmt("WebSocket ..........", result.websocket),
        _fmt("Database ...........", result.database),
        "",
        f"Overall status ..... {'OK' if result.overall_ok else 'FAIL'}",
    ]


def alert_lines(alerts) -> list[str]:
    lines = [f"alert_count: {len(alerts)}"]
    for alert in alerts:
        lines.append(
            f"{alert.created_at.isoformat()} | alert | id={alert.alert_id} | severity={alert.severity.value} | state={alert.state.value} | "
            f"type={alert.alert_type.value} | entity={alert.entity_type.value}:{alert.entity_id} | "
            f"summary={alert.summary}"
        )
    return lines


def market_opportunity_alert_lines(result) -> list[str]:
    lines = [
        "Market opportunity alert scan",
        f"scanned_count: {result.scanned_count}",
        f"relevant_count: {result.relevant_count}",
        f"created_alert_count: {len(result.created_alerts)}",
    ]
    for warning in result.warning_messages:
        lines.append(f"warning: {warning}")
    for alert in result.created_alerts:
        lines.append(
            f"{alert.created_at.isoformat()} | alert | id={alert.alert_id} | severity={alert.severity.value} | "
            f"state={alert.state.value} | type={alert.alert_type.value} | entity={alert.entity_type.value}:{alert.entity_id} | "
            f"summary={alert.summary}"
        )
    return lines


def saved_view_lines(saved_views) -> list[str]:
    lines = [f"saved_view_count: {len(saved_views)}"]
    for saved_view in saved_views:
        lines.append(
            f"{saved_view.created_at.isoformat()} | saved_view | name={saved_view.name} | "
            f"kind={saved_view.kind} | params={json.dumps(saved_view.params, sort_keys=True)}"
        )
    return lines


def digest_lines(digest: dict[str, object]) -> list[str]:
    analytics = digest["analytics"]
    return [
        f"digest_scope: {digest['scope']}",
        f"since_hours: {digest['since_hours']}",
        f"alerts_open: {digest['alerts_open']}",
        f"active_proposal_count: {analytics['active_proposal_count']}",
        f"approved_proposal_count: {analytics['approved_proposal_count']}",
        f"active_intent_count: {analytics['active_intent_count']}",
        f"terminal_intent_count: {analytics['terminal_intent_count']}",
        f"simulated_execution_count: {analytics['simulated_execution_count']}",
        f"outcome_analysis_summary: {digest['outcome_analysis_summary']}",
        f"group_count: {digest['group_count']}",
    ]


def probability_snapshot_lines(snapshot) -> list[str]:
    return kv_lines(
        [
            ("snapshot_id", snapshot.snapshot_id),
            ("market_id", snapshot.market_id),
            ("proposal_id", snapshot.proposal_id or "-"),
            ("fair_probability", f"{snapshot.probability.fair_probability:.4f}"),
            ("confidence", f"{snapshot.probability.confidence:.2f}"),
            ("model_agreement", snapshot.probability.model_agreement),
            ("trusted_source_present", snapshot.probability.trusted_source_present),
            ("source_types", ",".join(item.value for item in snapshot.probability.source_types) or "-"),
            ("source_count", snapshot.probability.source_count),
            ("key_factors", " | ".join(snapshot.probability.key_factors) or "-"),
            ("confidence_components", json.dumps(snapshot.probability.confidence_components, sort_keys=True)),
            (
                "source_type_contributions",
                json.dumps(snapshot.probability.source_type_contributions, sort_keys=True),
            ),
            (
                "evidence_records",
                " | ".join(
                    (
                        f"{item.source_type.value}:{item.source_name} "
                        f"weight={item.weight:.2f} contribution={item.contribution:.4f}"
                    )
                    for item in snapshot.probability.evidence_records
                )
                or "-",
            ),
            ("explanation", snapshot.probability.explanation or "-"),
            ("current_price", f"{snapshot.current_price:.4f}"),
            ("data_age_seconds", snapshot.data_age_seconds),
            ("created_at", snapshot.created_at.isoformat()),
        ]
    )


def research_summary_lines(snapshot) -> list[str]:
    return kv_lines(
        [
            ("market_id", snapshot.research_summary.market_id),
            ("proposal_id", snapshot.research_summary.proposal_id or "-"),
            ("research_summary", snapshot.research_summary.summary),
            ("research_key_factors", " | ".join(snapshot.research_summary.key_factors) or "-"),
            ("thesis_points", " | ".join(snapshot.research_summary.thesis_points) or "-"),
            ("risk_points", " | ".join(snapshot.research_summary.risk_points) or "-"),
            ("source_count", snapshot.research_summary.source_count),
            ("evidence_summary", " | ".join(snapshot.research_summary.evidence_summary) or "-"),
            ("snapshot_created_at", snapshot.created_at.isoformat()),
        ]
    )


def probability_drift_lines(drift) -> list[str]:
    fair_delta = "-" if drift.fair_probability_delta is None else f"{drift.fair_probability_delta:+.4f}"
    conf_delta = "-" if drift.confidence_delta is None else f"{drift.confidence_delta:+.4f}"
    source_delta = "-" if drift.source_count_delta is None else f"{drift.source_count_delta:+d}"
    latest_id = drift.latest_snapshot.snapshot_id
    previous_id = "-" if drift.previous_snapshot is None else drift.previous_snapshot.snapshot_id
    return kv_lines(
        [
            ("drift_scope", drift.scope),
            ("latest_snapshot_id", latest_id),
            ("previous_snapshot_id", previous_id),
            ("drift_summary", drift.drift_summary),
            ("fair_probability_delta", fair_delta),
            ("confidence_delta", conf_delta),
            ("source_count_delta", source_delta),
            ("confidence_component_deltas", json.dumps(drift.confidence_component_deltas, sort_keys=True)),
            (
                "source_type_contribution_deltas",
                json.dumps(drift.source_type_contribution_deltas, sort_keys=True),
            ),
            ("added_key_factors", " | ".join(drift.added_key_factors) or "-"),
            ("removed_key_factors", " | ".join(drift.removed_key_factors) or "-"),
            ("added_evidence_sources", " | ".join(drift.added_evidence_sources) or "-"),
            ("removed_evidence_sources", " | ".join(drift.removed_evidence_sources) or "-"),
        ]
    )


def decision_review_lines(review) -> list[str]:
    proposal = review.proposal
    snapshot = review.probability_snapshot
    drift = review.probability_drift
    intent = review.latest_intent
    execution = review.latest_execution
    return kv_lines(
        [
            ("decision_review_id", review.review_id),
            ("scope", review.scope),
            ("market_id", review.market_id),
            ("proposal_id", "-" if proposal is None else proposal.proposal_id),
            ("proposal_status", "-" if proposal is None else proposal.status.value),
            ("probability_snapshot_id", "-" if snapshot is None else snapshot.snapshot_id),
            ("probability_snapshot_created_at", "-" if snapshot is None else snapshot.created_at.isoformat()),
            ("probability_drift_summary", "-" if drift is None else drift.drift_summary or "insufficient_history"),
            ("confidence_outcome", review.confidence_outcome),
            ("probability_outcome", review.probability_outcome),
            ("execution_outcome", review.execution_outcome),
            ("latest_intent_id", "-" if intent is None else intent.intent_id),
            ("latest_intent_status", "-" if intent is None else intent.status.value),
            ("latest_execution_id", "-" if execution is None else execution.execution_id),
            ("latest_execution_status", "-" if execution is None else execution.status.value),
            (
                "latest_execution_slippage_bps",
                "-" if execution is None or execution.slippage_bps is None else f"{execution.slippage_bps:.2f}",
            ),
            ("summary", review.summary),
            ("created_at", review.created_at.isoformat()),
        ]
    )


def review_lines(rows) -> list[str]:
    lines = [f"reviews_count: {len(rows)}"]
    for row in rows:
        payload = json.loads(row["payload_json"])
        lines.append(
            f"{row['created_at']} | review | action={row['action']} | actor={row['actor']} | "
            f"note={row['note'] or '-'} | payload={json.dumps(payload, sort_keys=True)}"
        )
    return lines


def audit_lines(rows) -> list[str]:
    lines = [f"audit_count: {len(rows)}"]
    for row in rows:
        payload = json.loads(row["payload_json"])
        lines.append(
            f"{row['created_at']} | audit | event={row['event_type']} | message={row['message']} | "
            f"payload={json.dumps(payload, sort_keys=True)}"
        )
    return lines


def list_header_lines(scope: str, total_items: list, page_items: list, limit: int, offset: int, sort: str) -> list[str]:
    return [
        f"scope={scope} total={len(total_items)} returned={len(page_items)} limit={limit} offset={offset} sort={sort}",
        f"total_status_summary={status_summary(total_items)}",
        f"returned_status_summary={status_summary(page_items)}",
    ]


def latest_lookup_lines(label: str, entity_id: str, summary_line: str) -> list[str]:
    return [f"{label}: {entity_id}", summary_line]


def runtime_safety_lines(snapshot, include_exposure: bool) -> list[str]:
    lines = kv_lines(
        [
            ("mode", snapshot.mode.value),
            ("profile", snapshot.profile),
            ("kill_switch_enabled", snapshot.kill_switch_enabled),
            ("manual_approval_required", snapshot.manual_approval_required),
            ("auto_execute_disabled", snapshot.auto_execute_disabled),
            ("config_live_execution_enabled", snapshot.config_live_execution_enabled),
            ("mode_supports_live_execution", snapshot.mode_supports_live_execution),
            ("adapter_supports_live_execution", snapshot.adapter_supports_live_execution),
            ("guard_allows_live_execution", snapshot.guard_allows_live_execution),
            ("live_execution_enabled", snapshot.live_execution_enabled),
            ("live_execution_reason", snapshot.live_execution_reason),
            ("semi_auto_strict", snapshot.semi_auto_strict),
            ("execution_boundary", "semi_auto_strict" if snapshot.semi_auto_strict else "custom"),
        ]
    )
    if include_exposure:
        lines.extend(
            kv_lines(
                [
                    ("open_positions", snapshot.exposure.open_positions),
                    ("unresolved_exposure_usd", f"{snapshot.exposure.unresolved_exposure_usd:.2f}"),
                    ("unresolved_exposure_limit_usd", f"{snapshot.exposure.unresolved_exposure_limit_usd:.2f}"),
                    (
                        "unresolved_exposure_remaining_usd",
                        f"{snapshot.exposure.unresolved_exposure_remaining_usd:.2f}",
                    ),
                    ("bankroll_total_usd", f"{snapshot.exposure.total_bankroll_usd:.2f}"),
                    ("reserve_ratio", f"{snapshot.exposure.reserve_ratio:.2f}"),
                ]
            )
        )
    return lines
