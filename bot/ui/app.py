from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from urllib.parse import parse_qs

from bot.domain.enums import AlertState, WatchTargetType
from bot.domain.models import DecisionReviewSnapshot, OutcomeAnalysisSnapshot, SavedView
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.reporting import ReportingService
from bot.services.saved_views import SavedViewService
from bot.ui.presenter import (
    badge,
    chips,
    hero,
    item_link,
    json_block,
    kv_table,
    link_row,
    list_items,
    page,
    panel,
    shell_page,
    summary_cards,
)


@dataclass(slots=True)
class OperatorDashboardServices:
    proposal_service: ProposalLifecycleService
    execution_service: ExecutionPipelineService
    notifications_service: OperatorNotificationsService
    decision_review_service: DecisionReviewService
    execution_evaluation_service: ExecutionEvaluationService
    outcome_analysis_service: OutcomeAnalysisService
    saved_view_service: SavedViewService
    reporting_service: ReportingService


class OperatorDashboardApp:
    def __init__(self, services: OperatorDashboardServices) -> None:
        self.services = services

    def render_response(self, path: str, query_string: str = "") -> tuple[str, str]:
        query = parse_qs(query_string, keep_blank_values=False)
        try:
            status, body = self._route(path, query)
        except ValueError as exc:
            status = "404 Not Found"
            body = page(
                "Not Found",
                hero("Operator UI", "Requested entity is unavailable.")
                + panel("Lookup Error", f'<div class="empty">{escape(str(exc))}</div>'),
            )
        return status, body

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")
        status, body = self.render_response(path, query)
        payload = body.encode("utf-8")
        start_response(status, [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(payload)))])
        return [payload]

    def _route(self, path: str, query: dict[str, list[str]]) -> tuple[str, str]:
        if path == "/":
            return "200 OK", self._home()
        if path == "/proposals":
            return "200 OK", self._proposal_list(query)
        if path == "/proposals/latest-approved":
            return "200 OK", self._latest_approved_proposal()
        if path.startswith("/proposals/"):
            return "200 OK", self._proposal_detail(path.split("/", 2)[2])
        if path == "/intents":
            return "200 OK", self._intent_list(query)
        if path == "/intents/latest-terminal":
            return "200 OK", self._latest_terminal_intent()
        if path.startswith("/intents/"):
            return "200 OK", self._intent_detail(path.split("/", 2)[2])
        if path == "/alerts":
            return "200 OK", self._alert_list(query)
        if path.startswith("/alerts/"):
            return "200 OK", self._alert_action(path.split("/")[2], path.split("/")[3], query)
        if path == "/research":
            return "200 OK", self._research_index(query)
        if path.startswith("/research/proposals/"):
            return "200 OK", self._proposal_snapshot_detail(path.rsplit("/", 1)[1])
        if path.startswith("/research/markets/"):
            return "200 OK", self._market_snapshot_detail(path.rsplit("/", 1)[1])
        if path == "/decision-reviews":
            return "200 OK", self._decision_review_index(query)
        if path == "/decision-reviews/proposals/latest-approved":
            return "200 OK", self._latest_proposal_decision_review()
        if path.startswith("/decision-reviews/proposals/"):
            return "200 OK", self._proposal_decision_review(path.rsplit("/", 1)[1])
        if path.startswith("/decision-reviews/markets/"):
            return "200 OK", self._market_decision_review(path.rsplit("/", 1)[1])
        if path == "/analysis":
            return "200 OK", self._analysis(query)
        if path.startswith("/exports/decision-reviews/proposals/"):
            return "200 OK", self._export_decision_review(path.rsplit("/", 1)[1])
        if path.startswith("/exports/execution-evaluations/proposals/"):
            return "200 OK", self._export_execution_evaluation(proposal_id=path.rsplit("/", 1)[1])
        if path.startswith("/exports/execution-evaluations/intents/"):
            return "200 OK", self._export_execution_evaluation(intent_id=path.rsplit("/", 1)[1])
        if path == "/exports/outcome-analysis":
            return "200 OK", self._export_outcome_analysis(query)
        if path == "/views":
            return "200 OK", self._saved_view_list()
        if path == "/views/save-current":
            return "200 OK", self._save_current_filter(query)
        if path.startswith("/views/") and path.endswith("/clone"):
            return "200 OK", self._clone_saved_view(path.split("/")[2], query)
        if path.startswith("/views/") and path.endswith("/edit"):
            return "200 OK", self._edit_saved_view(path.split("/")[2], query)
        if path.startswith("/views/") and path.endswith("/run"):
            return "200 OK", self._run_saved_view(path.split("/")[2])
        if path.startswith("/views/"):
            return "200 OK", self._saved_view_detail(path.split("/")[2])
        return "404 Not Found", page(
            "Not Found",
            hero("Operator UI", "Unknown page") + panel("Missing", '<div class="empty">Route not found.</div>'),
        )

    def _home(self) -> str:
        active_proposals = self.services.proposal_service.list_active_proposals()
        active_intents = self.services.execution_service.list_active_intents()
        open_alerts = self.services.notifications_service.list_alerts(state=AlertState.OPEN)
        recent_alerts = self.services.notifications_service.list_alerts()[:5]
        recent_reviews = self.services.decision_review_service.list_recent(limit=3)
        recent_analyses = self.services.outcome_analysis_service.list_recent_snapshots(limit=3)
        latest_evaluations = self.services.execution_evaluation_service.list_recent(limit=3)
        latest_simulation = self.services.execution_service.latest_simulated_execution_overall()
        body = ""
        body += summary_cards(
            [
                ("open alerts", len(open_alerts), "operator action required"),
                ("active proposals", len(active_proposals), "pending or approved"),
                ("active intents", len(active_intents), "created or prepared"),
                ("saved views", len(self.services.saved_view_service.list_all()), "reusable filters"),
            ]
        )
        body += '<div class="grid">'
        body += panel(
            "Open Alerts",
            list_items(
                [self._alert_item(alert) for alert in open_alerts[:5]],
                "No open alerts.",
            )
            + link_row([("all alerts", "/alerts")]),
        )
        body += panel(
            "Active Proposals",
            list_items(
                [
                    self._status_item(
                        proposal.proposal_id,
                        proposal.status.value,
                        f"/proposals/{proposal.proposal_id}",
                        f"{proposal.market_title} | edge={proposal.edge:.4f} confidence={proposal.confidence:.2f}",
                        tone="good" if proposal.status.value == "approved" else "warn",
                    )
                    for proposal in active_proposals[:5]
                ],
                "No active proposals.",
            )
            + link_row([("all proposals", "/proposals?scope=active"), ("latest approved", "/proposals/latest-approved")]),
        )
        body += panel(
            "Active Intents",
            list_items(
                [
                    self._status_item(
                        intent.intent_id,
                        intent.status.value,
                        f"/intents/{intent.intent_id}",
                        f"proposal={intent.proposal_id} size={intent.size_usd:.2f}",
                    )
                    for intent in active_intents[:5]
                ],
                "No active intents.",
            )
            + link_row([("all intents", "/intents?scope=active"), ("latest terminal", "/intents/latest-terminal")]),
        )
        body += panel(
            "Latest Decision Reviews",
            list_items(
                [
                    self._status_item(
                        review.review_id,
                        review.confidence_outcome,
                        self._review_href(review),
                        review.summary,
                        tone="good" if review.probability_outcome.endswith("favor") else "warn",
                    )
                    for review in recent_reviews
                ],
                "No decision reviews yet.",
            )
            + link_row([("decision reviews", "/decision-reviews")]),
        )
        body += panel(
            "Latest Outcome Analysis",
            list_items(
                [
                    self._status_item(
                        snapshot.snapshot_id,
                        f"{snapshot.scope}:{snapshot.group_by}",
                        f"/analysis?scope={snapshot.scope}&group_by={snapshot.group_by}&latest=1",
                        snapshot.summary,
                        tone="good",
                    )
                    for snapshot in recent_analyses
                ],
                "No analysis snapshots yet.",
            )
            + link_row([("analysis", "/analysis"), ("saved views", "/views")]),
        )
        body += panel(
            "Latest Evaluations",
            list_items(
                [
                    self._status_item(
                        item.evaluation_id,
                        item.verdict,
                        f"/decision-reviews/proposals/{item.proposal_id}" if item.proposal_id else f"/intents/{item.intent_id}",
                        item.summary,
                        tone="good" if item.verdict in {"better_than_expected", "within_expected_range"} else "warn",
                    )
                    for item in latest_evaluations
                ],
                "No execution evaluations yet.",
            ),
        )
        body += panel(
            "Latest Simulation",
            '<div class="empty">No simulated execution yet.</div>'
            if latest_simulation is None
            else kv_table(
                [
                    ("execution_id", latest_simulation.execution_id),
                    ("intent_id", latest_simulation.intent_id),
                    ("status", latest_simulation.status.value),
                    ("filled_size_usd", f"{latest_simulation.filled_size_usd:.2f}"),
                    ("completion_reason", latest_simulation.completion_reason or "-"),
                ]
            )
            + link_row([("intent detail", f"/intents/{latest_simulation.intent_id}")]),
        )
        body += panel(
            "Recent Alerts",
            list_items([self._alert_item(alert) for alert in recent_alerts], "No alerts yet.")
            + link_row([("alert queue", "/alerts")]),
        )
        body += "</div>"
        return shell_page(
            "Operator Dashboard",
            "Operator Dashboard",
            "Thin dashboard over persisted operator services and workflows.",
            body,
        )

    def _proposal_list(self, query: dict[str, list[str]]) -> str:
        scope = self._query_value(query, "scope", "all")
        proposals = self._filtered_proposals(scope)
        market_id = self._query_value(query, "market_id")
        if market_id is not None:
            proposals = [item for item in proposals if item.market_id == market_id]
        body = hero("Proposals", "List and detail views backed by the proposal lifecycle service.")
        body += panel(
            "Proposal List",
            kv_table([("scope", scope), ("market_id", market_id or "-"), ("returned", len(proposals))])
            + link_row([("latest approved", "/proposals/latest-approved"), ("saved views", "/views")])
            + list_items(
                [
                    self._status_item(
                        proposal.proposal_id,
                        proposal.status.value,
                        f"/proposals/{proposal.proposal_id}",
                        (
                            f"{proposal.market_title} | category={proposal.market_category} "
                            f"confidence={proposal.confidence:.2f} size={proposal.current_size_usd:.2f}"
                        ),
                        tone="good" if proposal.status.value == "approved" else "warn",
                    )
                    for proposal in proposals
                ],
                "No proposals matched the filter.",
            ),
        )
        return page("Proposals", body)

    def _proposal_detail(self, proposal_id: str) -> str:
        proposal = self.services.proposal_service.latest_proposal_state(proposal_id)
        alerts = self.services.notifications_service.list_alerts_for_entity(WatchTargetType.PROPOSAL, proposal_id)
        latest_review = self.services.decision_review_service.latest_persisted_for_proposal(proposal_id)
        body = hero("Proposal Detail", "Detail page using the proposal lifecycle service.")
        body += panel(
            proposal.proposal_id,
            kv_table(
                [
                    ("market_id", proposal.market_id),
                    ("market_title", proposal.market_title),
                    ("market_category", proposal.market_category),
                    ("status", proposal.status.value),
                    ("confidence", f"{proposal.confidence:.2f}"),
                    ("edge", f"{proposal.edge:.4f}"),
                    ("size_usd", f"{proposal.current_size_usd:.2f}"),
                    ("limit_price", f"{proposal.current_limit_price:.4f}"),
                    ("expires_at", proposal.expires_at.isoformat()),
                ]
            )
            + chips(list(proposal.policy_decision.details.keys()), empty_message="no policy detail keys")
            + link_row(
                [
                    ("research snapshot", f"/research/proposals/{proposal.proposal_id}"),
                    ("integrated decision review", f"/decision-reviews/proposals/{proposal.proposal_id}"),
                ]
            ),
            meta="Thin detail view; proposal mutations remain in the service layer",
        )
        body += panel(
            "Thesis and Risks",
            chips(proposal.thesis, empty_message="no thesis points")
            + chips(proposal.risks, empty_message="no risk points"),
        )
        body += panel(
            "Alerts",
            list_items([self._alert_item(alert) for alert in alerts], "No proposal alerts."),
        )
        if latest_review is not None:
            body += panel(
                "Latest Decision Review",
                kv_table(
                    [
                        ("review_id", latest_review.review_id),
                        ("confidence_outcome", latest_review.confidence_outcome),
                        ("probability_outcome", latest_review.probability_outcome),
                        ("execution_outcome", latest_review.execution_outcome),
                    ]
                )
                + link_row([("open review", f"/decision-reviews/proposals/{proposal.proposal_id}")]),
            )
        return page(f"Proposal {proposal.proposal_id}", body)

    def _latest_approved_proposal(self) -> str:
        proposal = self.services.proposal_service.latest_approved_proposal()
        body = hero("Latest Approved Proposal", "Latest lookup page.")
        content = '<div class="empty">No approved proposal.</div>'
        if proposal is not None:
            content = kv_table(
                [
                    ("proposal_id", proposal.proposal_id),
                    ("market_title", proposal.market_title),
                    ("status", proposal.status.value),
                    ("updated_at", proposal.updated_at.isoformat()),
                ]
            ) + link_row(
                [
                    ("open detail", f"/proposals/{proposal.proposal_id}"),
                    ("research", f"/research/proposals/{proposal.proposal_id}"),
                    ("decision review", f"/decision-reviews/proposals/{proposal.proposal_id}"),
                ]
            )
        body += panel("Latest Approved", content)
        return page("Latest Approved Proposal", body)

    def _intent_list(self, query: dict[str, list[str]]) -> str:
        scope = self._query_value(query, "scope", "all")
        intents = self._filtered_intents(scope)
        proposal_id = self._query_value(query, "proposal_id")
        if proposal_id is not None:
            intents = [item for item in intents if item.proposal_id == proposal_id]
        body = hero("Intents", "Thin UI over execution pipeline list/detail services.")
        body += panel(
            "Intent List",
            kv_table([("scope", scope), ("proposal_id", proposal_id or "-"), ("returned", len(intents))])
            + link_row([("latest terminal", "/intents/latest-terminal"), ("saved views", "/views")])
            + list_items(
                [
                    self._status_item(
                        intent.intent_id,
                        intent.status.value,
                        f"/intents/{intent.intent_id}",
                        f"proposal={intent.proposal_id} size={intent.size_usd:.2f} limit={intent.limit_price:.4f}",
                    )
                    for intent in intents
                ],
                "No intents matched the filter.",
            ),
        )
        return page("Intents", body)

    def _intent_detail(self, intent_id: str) -> str:
        intent = self.services.execution_service.latest_intent_state(intent_id)
        execution = self.services.execution_service.latest_simulated_execution(intent_id)
        evaluation = self.services.execution_evaluation_service.latest_persisted_for_intent(intent_id)
        timeline = self.services.execution_service.list_execution_timeline(intent_id)
        alerts = self.services.notifications_service.list_alerts_for_entity(WatchTargetType.INTENT, intent_id)
        body = hero("Intent Detail", "Detail page using the execution pipeline service.")
        rows = [
            ("proposal_id", intent.proposal_id),
            ("market_id", intent.market_id),
            ("status", intent.status.value),
            ("side", intent.side),
            ("size_usd", f"{intent.size_usd:.2f}"),
            ("limit_price", f"{intent.limit_price:.4f}"),
            ("reason", intent.reason),
            ("timeline_events", len(timeline)),
        ]
        if execution is not None:
            rows.extend(
                [
                    ("latest_execution_status", execution.status.value),
                    ("reference_price", f"{execution.reference_price:.4f}"),
                    ("simulated_price", "-" if execution.simulated_price is None else f"{execution.simulated_price:.4f}"),
                    ("completion_reason", execution.completion_reason or "-"),
                    ("latency_ms", "-" if execution.latency_ms is None else execution.latency_ms),
                ]
            )
        body += panel(intent.intent_id, kv_table(rows) + link_row([("proposal detail", f"/proposals/{intent.proposal_id}")]))
        if evaluation is not None:
            body += panel(
                "Latest Execution Evaluation",
                kv_table([("verdict", evaluation.verdict), ("summary", evaluation.summary)]),
            )
        body += panel(
            "Timeline",
            list_items(
                [
                    item_link(
                        event.event_type,
                        f"fragment={event.fragment_index} size={event.size_usd:.2f}",
                        f"/intents/{intent_id}",
                        meta=f"price={event.price:.4f} latency_ms={event.latency_ms}",
                    )
                    for event in timeline
                ],
                "No simulated fill events.",
            ),
        )
        body += panel("Alerts", list_items([self._alert_item(alert) for alert in alerts], "No intent alerts."))
        return page(f"Intent {intent.intent_id}", body)

    def _latest_terminal_intent(self) -> str:
        intent = self.services.execution_service.latest_terminal_intent()
        body = hero("Latest Terminal Intent", "Latest lookup page.")
        content = '<div class="empty">No terminal intent.</div>'
        if intent is not None:
            content = kv_table(
                [
                    ("intent_id", intent.intent_id),
                    ("proposal_id", intent.proposal_id),
                    ("status", intent.status.value),
                    ("updated_at", intent.updated_at.isoformat()),
                ]
            ) + link_row([("open detail", f"/intents/{intent.intent_id}"), ("proposal", f"/proposals/{intent.proposal_id}")])
        body += panel("Latest Terminal", content)
        return page("Latest Terminal Intent", body)

    def _alert_list(self, query: dict[str, list[str]]) -> str:
        state_value = self._query_value(query, "state")
        state = None if state_value is None else AlertState(state_value)
        watchlist_only = self._query_value(query, "watchlist_only", "0") == "1"
        alerts = self.services.notifications_service.list_alerts(watchlist_only=watchlist_only, state=state)
        entity_type = self._query_value(query, "entity_type")
        entity_id = self._query_value(query, "entity_id")
        if entity_type is not None and entity_id is not None:
            alerts = [alert for alert in alerts if alert.entity_type.value == entity_type and alert.entity_id == entity_id]
        body = hero("Alerts", "Alert list view with state filtering and lifecycle actions.")
        body += panel(
            "Alert List",
            kv_table(
                [
                    ("state", state_value or "-"),
                    ("watchlist_only", watchlist_only),
                    ("entity", "-" if entity_id is None else f"{entity_type}:{entity_id}"),
                    ("returned", len(alerts)),
                ]
            )
            + list_items([self._alert_item(alert, include_actions=True) for alert in alerts], "No alerts matched the filter."),
        )
        return page("Alerts", body)

    def _alert_action(self, alert_id: str, action: str, query: dict[str, list[str]]) -> str:
        if action == "acknowledge":
            alert = self.services.notifications_service.acknowledge_alert(alert_id)
        elif action == "dismiss":
            alert = self.services.notifications_service.dismiss_alert(alert_id)
        elif action == "resolve":
            alert = self.services.notifications_service.resolve_alert(alert_id)
        else:
            raise ValueError(f"Unknown alert action: {action}")
        return_to = self._query_value(query, "return_to", "/alerts") or "/alerts"
        flash = f"Alert {alert.alert_id} moved to {alert.state.value}."
        body = panel(
            alert.alert_id,
            kv_table(
                [
                    ("alert_type", alert.alert_type.value),
                    ("state", alert.state.value),
                    ("entity", f"{alert.entity_type.value}:{alert.entity_id}"),
                    ("summary", alert.summary),
                ]
            )
            + link_row([("back to list", return_to), ("entity detail", self._entity_href(alert.entity_type.value, alert.entity_id))]),
        )
        return shell_page(
            "Alert Updated",
            "Alert Updated",
            "Alert lifecycle transition applied through the notification service.",
            body,
            flash=flash,
        )

    def _research_index(self, query: dict[str, list[str]]) -> str:
        proposal = self.services.proposal_service.latest_approved_proposal()
        market_id = self._query_value(query, "market_id")
        body = hero("Research Snapshots", "Latest probability and research views stay read-only in the UI.")
        body += panel(
            "Latest Proposal Research",
            '<div class="empty">No approved proposal research available.</div>'
            if proposal is None
            else kv_table([("proposal_id", proposal.proposal_id), ("market_id", proposal.market_id), ("market_title", proposal.market_title)])
            + link_row(
                [
                    ("proposal snapshot", f"/research/proposals/{proposal.proposal_id}"),
                    ("integrated decision review", f"/decision-reviews/proposals/{proposal.proposal_id}"),
                    ("decision review export", f"/exports/decision-reviews/proposals/{proposal.proposal_id}"),
                ]
            ),
        )
        body += panel(
            "Market Lookup",
            kv_table([("market_id", market_id or "-")])
            + (
                '<div class="empty">Provide ?market_id=... to jump to a market snapshot.</div>'
                if market_id is None
                else link_row(
                    [
                        ("market snapshot", f"/research/markets/{market_id}"),
                        ("market decision review", f"/decision-reviews/markets/{market_id}"),
                    ]
                )
            ),
        )
        return page("Research", body)

    def _proposal_snapshot_detail(self, proposal_id: str) -> str:
        snapshot = self.services.proposal_service.latest_probability_snapshot_for_proposal(proposal_id)
        drift = self.services.proposal_service.compare_probability_snapshots_for_proposal(proposal_id)
        body = hero("Proposal Snapshot", "Probability and research snapshot detail.")
        body += panel(
            f"Snapshot {snapshot.snapshot_id}",
            kv_table(
                [
                    ("proposal_id", snapshot.proposal_id or "-"),
                    ("market_id", snapshot.market_id),
                    ("fair_probability", f"{snapshot.probability.fair_probability:.4f}"),
                    ("confidence", f"{snapshot.probability.confidence:.2f}"),
                    ("current_price", f"{snapshot.current_price:.4f}"),
                    ("source_count", snapshot.probability.source_count),
                    ("created_at", snapshot.created_at.isoformat()),
                ]
            )
            + chips(snapshot.probability.key_factors, empty_message="no key factors"),
        )
        body += panel(
            "Research Summary",
            kv_table(
                [
                    ("summary", snapshot.research_summary.summary),
                    ("source_count", snapshot.research_summary.source_count),
                    ("data_age_seconds", snapshot.data_age_seconds),
                    ("drift_summary", drift.drift_summary or "insufficient history"),
                ]
            )
            + chips(snapshot.research_summary.evidence_summary, empty_message="no evidence summary"),
        )
        body += panel(
            "Evidence and Drift",
            chips(
                [f"{record.source_name}:{record.source_type.value}:{record.weight:.2f}" for record in snapshot.probability.evidence_records],
                empty_message="no evidence records",
            )
            + chips(
                [f"{key}={value:+.4f}" for key, value in sorted(drift.source_type_contribution_deltas.items())],
                empty_message="no source contribution deltas",
            ),
        )
        return page("Proposal Snapshot", body)

    def _market_snapshot_detail(self, market_id: str) -> str:
        snapshot = self.services.proposal_service.latest_probability_snapshot_for_market(market_id)
        drift = self.services.proposal_service.compare_probability_snapshots_for_market(market_id)
        body = hero("Market Snapshot", "Latest market-level probability and research snapshot.")
        body += panel(
            f"Market {snapshot.market_id}",
            kv_table(
                [
                    ("proposal_id", snapshot.proposal_id or "-"),
                    ("fair_probability", f"{snapshot.probability.fair_probability:.4f}"),
                    ("confidence", f"{snapshot.probability.confidence:.2f}"),
                    ("research_summary", snapshot.research_summary.summary),
                    ("drift_summary", drift.drift_summary or "insufficient history"),
                    ("created_at", snapshot.created_at.isoformat()),
                ]
            )
            + chips(snapshot.research_summary.evidence_summary, empty_message="no evidence summary"),
        )
        return page("Market Snapshot", body)

    def _decision_review_index(self, query: dict[str, list[str]]) -> str:
        proposal = self.services.proposal_service.latest_approved_proposal()
        market_id = self._query_value(query, "market_id")
        reviews = self.services.decision_review_service.list_recent(limit=10)
        body = hero("Decision Reviews", "Integrated post-hoc context built from persisted services.")
        body += panel(
            "Latest Review Lookup",
            '<div class="empty">No approved proposal decision review available.</div>'
            if proposal is None
            else kv_table([("proposal_id", proposal.proposal_id), ("market_id", proposal.market_id)])
            + link_row(
                [
                    ("latest approved review", "/decision-reviews/proposals/latest-approved"),
                    ("proposal review", f"/decision-reviews/proposals/{proposal.proposal_id}"),
                ]
            ),
        )
        body += panel(
            "Market Review Lookup",
            kv_table([("market_id", market_id or "-")])
            + (
                '<div class="empty">Provide ?market_id=... to open a market decision review.</div>'
                if market_id is None
                else link_row([("market review", f"/decision-reviews/markets/{market_id}")])
            ),
        )
        body += panel(
            "Recent Decision Reviews",
            list_items(
                [
                    self._status_item(
                        review.review_id,
                        review.confidence_outcome,
                        self._review_href(review),
                        review.summary,
                    )
                    for review in reviews
                ],
                "No persisted decision reviews.",
            ),
        )
        return page("Decision Reviews", body)

    def _latest_proposal_decision_review(self) -> str:
        proposal = self.services.proposal_service.latest_approved_proposal()
        body = hero("Latest Proposal Decision Review", "Latest approved proposal review lookup.")
        if proposal is None:
            body += panel("Latest Review", '<div class="empty">No approved proposal.</div>')
            return page("Latest Proposal Decision Review", body)
        return self._proposal_decision_review(proposal.proposal_id)

    def _proposal_decision_review(self, proposal_id: str) -> str:
        snapshot = self.services.decision_review_service.latest_persisted_for_proposal(proposal_id)
        if snapshot is None:
            self.services.decision_review_service.create_for_proposal(proposal_id)
            snapshot = self.services.decision_review_service.latest_persisted_for_proposal(proposal_id)
        if snapshot is None:
            raise ValueError(f"No decision review for proposal: {proposal_id}")
        evaluation = self.services.execution_evaluation_service.latest_persisted_for_proposal(proposal_id)
        if evaluation is None and snapshot.intent_id is not None:
            self.services.execution_evaluation_service.evaluate_proposal(proposal_id)
            evaluation = self.services.execution_evaluation_service.latest_persisted_for_proposal(proposal_id)
        return page(
            "Decision Review",
            hero("Decision Review", "Integrated operator review of proposal, research, drift, intent, execution, and evaluation.")
            + self._integrated_review_panels(snapshot, evaluation),
        )

    def _market_decision_review(self, market_id: str) -> str:
        snapshot = self.services.decision_review_service.latest_persisted_for_market(market_id)
        if snapshot is None:
            self.services.decision_review_service.create_for_market(market_id)
            snapshot = self.services.decision_review_service.latest_persisted_for_market(market_id)
        if snapshot is None:
            raise ValueError(f"No decision review for market: {market_id}")
        evaluation = None
        if snapshot.proposal_id is not None:
            evaluation = self.services.execution_evaluation_service.latest_persisted_for_proposal(snapshot.proposal_id)
        return page(
            "Market Decision Review",
            hero("Market Decision Review", "Integrated market-level operator review.")
            + self._integrated_review_panels(snapshot, evaluation),
        )

    def _analysis(self, query: dict[str, list[str]]) -> str:
        scope = self._query_value(query, "scope", "outcomes")
        group_by = self._query_value(query, "group_by", "market")
        latest_only = self._query_value(query, "latest", "0") == "1"
        since_hours = self._query_int(query, "since_hours")
        if latest_only:
            snapshot = self.services.outcome_analysis_service.latest_snapshot(scope, group_by)
            if snapshot is None:
                snapshot = self._build_analysis(scope, group_by, since_hours)
        else:
            snapshot = self._build_analysis(scope, group_by, since_hours)
        body = hero("Outcome Analysis", "Grouped operator analysis using persisted reviews and evaluations.")
        body += panel(
            "Analysis Summary",
            kv_table(
                [
                    ("scope", snapshot.scope),
                    ("group_by", snapshot.group_by),
                    ("since_hours", snapshot.since_hours if snapshot.since_hours is not None else "-"),
                    ("summary", snapshot.summary),
                ]
            )
            + link_row(
                [
                    ("saved views", "/views"),
                    ("export analysis", f"/exports/outcome-analysis?scope={snapshot.scope}&group_by={snapshot.group_by}"),
                ]
            ),
        )
        body += panel(
            "Groups",
            list_items(
                [
                    self._status_item(
                        group.group_value,
                        f"reviews={group.review_count} evaluations={group.evaluation_count}",
                        f"/analysis?scope={snapshot.scope}&group_by={snapshot.group_by}&latest=1",
                        (
                            f"confidence_held={group.confidence_held_count} "
                            f"confidence_degraded={group.confidence_degraded_count} "
                            f"verdicts={group.verdict_counts}"
                        ),
                        tone="good",
                    )
                    for group in snapshot.groups
                ],
                "No grouped analysis available.",
            ),
        )
        return page("Outcome Analysis", body)

    def _saved_view_list(self) -> str:
        views = self.services.saved_view_service.list_all()
        body = panel(
            "Saved View List",
            list_items(
                [
                    self._status_item(
                        saved.name,
                        saved.kind,
                        f"/views/{saved.name}",
                        f"params={saved.params}",
                        tone="good",
                    )
                    + link_row(
                        [
                            ("run", f"/views/{saved.name}/run"),
                            ("clone", f"/views/{saved.name}/clone?name={saved.name}-copy"),
                            ("edit", f"/views/{saved.name}/edit"),
                        ]
                    )
                    for saved in views
                ],
                "No saved views configured.",
            )
            + link_row(
                [
                    ("save current proposals filter", "/views/save-current?name=active-proposals-ui&kind=proposals_list&scope=active"),
                    ("save current analysis filter", "/views/save-current?name=market-analysis-ui&kind=analysis_outcomes&group_by=market"),
                ]
            ),
        )
        return shell_page(
            "Saved Views",
            "Saved Views",
            "Reusable filters and analysis routes backed by the saved view service.",
            body,
        )

    def _saved_view_detail(self, name: str) -> str:
        saved = self.services.saved_view_service.get(name)
        if saved is None:
            raise ValueError(f"Unknown saved view: {name}")
        body = panel(
            saved.name,
            kv_table([("kind", saved.kind), ("created_at", saved.created_at.isoformat()), ("params", saved.params)])
            + link_row(
                [
                    ("run saved view", f"/views/{saved.name}/run"),
                    ("clone", f"/views/{saved.name}/clone?name={saved.name}-copy"),
                    ("edit", f"/views/{saved.name}/edit"),
                    ("all saved views", "/views"),
                ]
            ),
        )
        return shell_page(
            f"Saved View {saved.name}",
            "Saved View",
            "Saved filter definition for list or analysis workflows.",
            body,
        )

    def _run_saved_view(self, name: str) -> str:
        saved = self.services.saved_view_service.get(name)
        if saved is None:
            raise ValueError(f"Unknown saved view: {name}")
        if saved.kind == "proposals_list":
            return self._proposal_list(self._params_query(saved, "scope", "all"))
        if saved.kind == "intents_list":
            return self._intent_list(self._params_query(saved, "scope", "all"))
        if saved.kind == "alerts_list":
            return self._alert_list(self._params_query(saved))
        if saved.kind == "analysis_outcomes":
            return self._analysis(self._params_query(saved, "scope", "outcomes"))
        if saved.kind == "analysis_learning":
            return self._analysis(self._params_query(saved, "scope", "learning_summary"))
        raise ValueError(f"Unsupported saved view kind: {saved.kind}")

    def _clone_saved_view(self, name: str, query: dict[str, list[str]]) -> str:
        saved = self.services.saved_view_service.get(name)
        if saved is None:
            raise ValueError(f"Unknown saved view: {name}")
        new_name = self._query_value(query, "name", f"{name}-copy")
        cloned = self.services.saved_view_service.save(new_name, saved.kind, dict(saved.params))
        return shell_page(
            "Saved View Cloned",
            "Saved View Cloned",
            "Saved view duplicated through the saved view service.",
            panel(
                cloned.name,
                kv_table([("kind", cloned.kind), ("params", cloned.params)])
                + link_row([("open cloned view", f"/views/{cloned.name}"), ("run cloned view", f"/views/{cloned.name}/run")]),
            ),
            flash=f"Saved view {name} cloned to {cloned.name}.",
        )

    def _edit_saved_view(self, name: str, query: dict[str, list[str]]) -> str:
        saved = self.services.saved_view_service.get(name)
        if saved is None:
            raise ValueError(f"Unknown saved view: {name}")
        merged = dict(saved.params)
        for key, values in query.items():
            if key == "name":
                continue
            merged[key] = self._coerce_query_value(values[-1])
        target_name = self._query_value(query, "name", name)
        updated = self.services.saved_view_service.save(target_name, saved.kind, merged)
        return shell_page(
            "Saved View Updated",
            "Saved View Updated",
            "Saved view parameters updated through the saved view service.",
            panel(
                updated.name,
                kv_table([("kind", updated.kind), ("params", updated.params)])
                + link_row([("open view", f"/views/{updated.name}"), ("run view", f"/views/{updated.name}/run"), ("all views", "/views")]),
            ),
            flash=f"Saved view {name} updated.",
        )

    def _save_current_filter(self, query: dict[str, list[str]]) -> str:
        name = self._query_value(query, "name")
        kind = self._query_value(query, "kind")
        if name is None or kind is None:
            raise ValueError("save-current-filter requires name and kind")
        params: dict[str, object] = {}
        for key, values in query.items():
            if key in {"name", "kind"}:
                continue
            params[key] = self._coerce_query_value(values[-1])
        saved = self.services.saved_view_service.save(name, kind, params)
        return shell_page(
            "Current Filter Saved",
            "Current Filter Saved",
            "Current UI filter saved through the saved view service.",
            panel(
                saved.name,
                kv_table([("kind", saved.kind), ("params", saved.params)])
                + link_row([("open saved view", f"/views/{saved.name}"), ("run saved view", f"/views/{saved.name}/run")]),
            ),
            flash=f"Saved current filter as {saved.name}.",
        )

    def _export_decision_review(self, proposal_id: str) -> str:
        payload = self.services.reporting_service.export_decision_review(proposal_id)
        return shell_page(
            "Decision Review Export",
            "Decision Review Export",
            "Thin export view backed by the reporting service.",
            panel(
                "Payload",
                json_block(json.dumps(payload, indent=2, sort_keys=True))
                + link_row([("back to decision review", f"/decision-reviews/proposals/{proposal_id}")]),
            ),
        )

    def _export_execution_evaluation(self, proposal_id: str | None = None, intent_id: str | None = None) -> str:
        payload = self.services.reporting_service.export_execution_evaluation(proposal_id=proposal_id, intent_id=intent_id)
        back_href = f"/decision-reviews/proposals/{proposal_id}" if proposal_id is not None else f"/intents/{intent_id}"
        return shell_page(
            "Execution Evaluation Export",
            "Execution Evaluation Export",
            "Thin export view backed by the reporting service.",
            panel(
                "Payload",
                json_block(json.dumps(payload, indent=2, sort_keys=True))
                + link_row([("back", back_href)]),
            ),
        )

    def _export_outcome_analysis(self, query: dict[str, list[str]]) -> str:
        scope = self._query_value(query, "scope", "outcomes") or "outcomes"
        group_by = self._query_value(query, "group_by", "market") or "market"
        since_hours = self._query_int(query, "since_hours")
        payload = self.services.reporting_service.export_outcome_analysis(scope, group_by, since_hours)
        return shell_page(
            "Outcome Analysis Export",
            "Outcome Analysis Export",
            "Thin export view backed by the reporting service.",
            panel(
                "Payload",
                json_block(json.dumps(payload, indent=2, sort_keys=True))
                + link_row([("back to analysis", f"/analysis?scope={scope}&group_by={group_by}")]),
            ),
        )

    def _filtered_proposals(self, scope: str):
        if scope == "active":
            return self.services.proposal_service.list_active_proposals()
        if scope == "approved":
            return self.services.proposal_service.list_approved_proposals()
        return self.services.proposal_service.list_proposals()

    def _filtered_intents(self, scope: str):
        if scope == "active":
            return self.services.execution_service.list_active_intents()
        if scope == "terminal":
            return self.services.execution_service.list_terminal_intents()
        return self.services.execution_service.list_all_intents()

    def _build_analysis(self, scope: str, group_by: str, since_hours: int | None):
        if scope == "learning_summary":
            return self.services.outcome_analysis_service.summarize_learning(group_by, since_hours)
        return self.services.outcome_analysis_service.summarize_outcomes(group_by, since_hours)

    def _integrated_review_panels(self, snapshot: DecisionReviewSnapshot, evaluation) -> str:
        proposal = snapshot.payload.get("proposal")
        probability_snapshot = snapshot.payload.get("probability_snapshot", {})
        probability_drift = snapshot.payload.get("probability_drift", {})
        intent = snapshot.payload.get("intent")
        execution = snapshot.payload.get("execution")
        outcomes = snapshot.payload.get("outcomes", {})
        body = '<div class="grid">'
        body += panel(
            "Review Overview",
            kv_table(
                [
                    ("review_id", snapshot.review_id),
                    ("scope", snapshot.scope),
                    ("market_id", snapshot.market_id),
                    ("proposal_id", snapshot.proposal_id or "-"),
                    ("summary", snapshot.summary),
                ]
            )
            + chips(
                [
                    f"confidence={outcomes.get('confidence', '-')}",
                    f"probability={outcomes.get('probability', '-')}",
                    f"execution={outcomes.get('execution', '-')}",
                ]
            )
            + link_row(
                []
                if snapshot.proposal_id is None
                else [("export decision review", f"/exports/decision-reviews/proposals/{snapshot.proposal_id}")]
            ),
        )
        body += panel(
            "Proposal",
            '<div class="empty">No proposal linked.</div>'
            if proposal is None
            else kv_table(
                [
                    ("proposal_id", proposal.get("proposal_id", "-")),
                    ("status", proposal.get("status", "-")),
                    ("side", proposal.get("side", "-")),
                    ("market_price", proposal.get("market_price", "-")),
                    ("fair_probability", proposal.get("fair_probability", "-")),
                    ("confidence", proposal.get("confidence", "-")),
                ]
            ),
        )
        body += panel(
            "Probability Snapshot",
            kv_table(
                [
                    ("snapshot_id", probability_snapshot.get("snapshot_id", "-")),
                    ("fair_probability", probability_snapshot.get("fair_probability", "-")),
                    ("confidence", probability_snapshot.get("confidence", "-")),
                    ("source_count", probability_snapshot.get("source_count", "-")),
                    ("created_at", probability_snapshot.get("created_at", "-")),
                ]
            )
            + chips(probability_snapshot.get("key_factors", []), empty_message="no key factors"),
        )
        body += panel(
            "Probability Drift",
            kv_table(
                [
                    ("previous_snapshot_id", probability_drift.get("previous_snapshot_id", "-")),
                    ("fair_probability_delta", probability_drift.get("fair_probability_delta", "-")),
                    ("confidence_delta", probability_drift.get("confidence_delta", "-")),
                    ("source_count_delta", probability_drift.get("source_count_delta", "-")),
                    ("drift_summary", probability_drift.get("drift_summary", "-")),
                ]
            )
            + chips(probability_drift.get("added_key_factors", []), empty_message="no added factors")
            + chips(probability_drift.get("removed_key_factors", []), empty_message="no removed factors"),
        )
        body += panel(
            "Intent and Execution",
            (
                '<div class="empty">No linked intent.</div>'
                if intent is None
                else kv_table(
                    [
                        ("intent_id", intent.get("intent_id", "-")),
                        ("status", intent.get("status", "-")),
                        ("size_usd", intent.get("size_usd", "-")),
                        ("limit_price", intent.get("limit_price", "-")),
                        ("updated_at", intent.get("updated_at", "-")),
                    ]
                )
            )
            + (
                '<div class="empty">No simulated execution.</div>'
                if execution is None
                else kv_table(
                    [
                        ("execution_id", execution.get("execution_id", "-")),
                        ("status", execution.get("status", "-")),
                        ("reference_price", execution.get("reference_price", "-")),
                        ("simulated_price", execution.get("simulated_price", "-")),
                        ("slippage_bps", execution.get("slippage_bps", "-")),
                        ("filled_size_usd", execution.get("filled_size_usd", "-")),
                        ("fill_timestamp", execution.get("fill_timestamp", "-")),
                    ]
                )
            ),
        )
        body += panel(
            "Execution Evaluation",
            '<div class="empty">No execution evaluation snapshot.</div>'
            if evaluation is None
            else kv_table(
                [
                    ("verdict", evaluation.verdict),
                    ("summary", evaluation.summary),
                    ("price_delta", evaluation.payload.get("price_delta", "-")),
                    ("size_fill_ratio", evaluation.payload.get("size_fill_ratio", "-")),
                    ("latency_delta_ms", evaluation.payload.get("latency_delta_ms", "-")),
                    ("actual_completion_reason", evaluation.payload.get("actual_completion_reason", "-")),
                ]
            )
            + link_row(
                []
                if snapshot.intent_id is None and snapshot.proposal_id is None
                else [
                    (
                        "export evaluation",
                        f"/exports/execution-evaluations/proposals/{snapshot.proposal_id}"
                        if snapshot.proposal_id is not None
                        else f"/exports/execution-evaluations/intents/{snapshot.intent_id}",
                    )
                ]
            ),
        )
        body += "</div>"
        return body

    def _alert_item(self, alert, include_actions: bool = False) -> str:
        return_to = "/alerts"
        content = self._status_item(
            alert.summary,
            alert.state.value,
            self._entity_href(alert.entity_type.value, alert.entity_id),
            f"{alert.alert_type.value} | severity={alert.severity.value} | entity={alert.entity_type.value}:{alert.entity_id}",
            tone=self._alert_tone(alert.state.value),
        )
        if not include_actions:
            return content
        actions = []
        if alert.state == AlertState.OPEN:
            actions.extend(
                [
                    ("acknowledge", f"/alerts/{alert.alert_id}/acknowledge?return_to={return_to}"),
                    ("dismiss", f"/alerts/{alert.alert_id}/dismiss?return_to={return_to}"),
                    ("resolve", f"/alerts/{alert.alert_id}/resolve?return_to={return_to}"),
                ]
            )
        elif alert.state == AlertState.ACKNOWLEDGED:
            actions.extend(
                [
                    ("dismiss", f"/alerts/{alert.alert_id}/dismiss?return_to={return_to}"),
                    ("resolve", f"/alerts/{alert.alert_id}/resolve?return_to={return_to}"),
                ]
            )
        return content + link_row(actions)

    def _status_item(self, title: str, status: str, href: str, meta: str, tone: str = "warn") -> str:
        return f"{badge(status, tone)} {item_link(title, status, href, meta=meta)}"

    def _review_href(self, review: DecisionReviewSnapshot) -> str:
        if review.scope == "proposal" and review.proposal_id is not None:
            return f"/decision-reviews/proposals/{review.proposal_id}"
        return f"/decision-reviews/markets/{review.market_id}"

    def _params_query(self, saved: SavedView, *defaults: tuple[str, str] | str) -> dict[str, list[str]]:
        params = {key: [str(value)] for key, value in saved.params.items()}
        for default in defaults:
            if isinstance(default, tuple):
                key, value = default
            else:
                continue
            params.setdefault(key, [value])
        return params

    def _entity_href(self, entity_type: str, entity_id: str) -> str:
        if entity_type == WatchTargetType.PROPOSAL.value:
            return f"/proposals/{entity_id}"
        if entity_type == WatchTargetType.INTENT.value:
            return f"/intents/{entity_id}"
        if entity_type == WatchTargetType.MARKET.value:
            return f"/research/markets/{entity_id}"
        return "/alerts"

    def _alert_tone(self, state: str) -> str:
        if state == AlertState.RESOLVED.value:
            return "good"
        if state == AlertState.DISMISSED.value:
            return "bad"
        return "warn"

    def _query_value(self, query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
        values = query.get(key)
        return default if not values else values[-1]

    def _query_int(self, query: dict[str, list[str]], key: str) -> int | None:
        value = self._query_value(query, key)
        return None if value is None else int(value)

    def _coerce_query_value(self, value: str) -> object:
        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        if value.isdigit():
            return int(value)
        try:
            return float(value) if "." in value else value
        except ValueError:
            return value
