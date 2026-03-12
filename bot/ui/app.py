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
from bot.services.market_sync import LiveMarketDataService
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
    market_data_service: LiveMarketDataService | None = None


class OperatorDashboardApp:
    FIELD_LABELS = {
        "scope": "Область",
        "market_id": "ID рынка",
        "proposal_id": "ID предложения",
        "intent_id": "ID намерения",
        "review_id": "ID разбора",
        "snapshot_id": "ID снимка",
        "previous_snapshot_id": "ID предыдущего снимка",
        "evaluation_id": "ID оценки",
        "execution_id": "ID исполнения",
        "market_title": "Название рынка",
        "market_category": "Категория рынка",
        "status": "Статус",
        "confidence": "Уверенность",
        "edge": "Преимущество",
        "size_usd": "Размер, USD",
        "filled_size_usd": "Исполнено, USD",
        "limit_price": "Лимитная цена",
        "current_price": "Текущая цена",
        "market_price": "Рыночная цена",
        "fair_probability": "Справедливая вероятность",
        "source_count": "Количество источников",
        "created_at": "Создано",
        "updated_at": "Обновлено",
        "expires_at": "Истекает",
        "returned": "Возвращено",
        "state": "Состояние",
        "watchlist_only": "Только watchlist",
        "entity": "Сущность",
        "alert_type": "Тип алерта",
        "summary": "Сводка",
        "reason": "Причина",
        "side": "Сторона",
        "timeline_events": "Событий в таймлайне",
        "latest_execution_status": "Статус последнего исполнения",
        "reference_price": "Опорная цена",
        "best_bid": "Лучшая bid цена",
        "best_ask": "Лучшая ask цена",
        "simulated_price": "Смоделированная цена",
        "completion_reason": "Причина завершения",
        "latency_ms": "Задержка, мс",
        "verdict": "Вердикт",
        "research_summary": "Сводка исследования",
        "data_age_seconds": "Возраст данных, сек",
        "drift_summary": "Сводка дрейфа",
        "group_by": "Группировка",
        "since_hours": "Окно, часов",
        "kind": "Тип",
        "params": "Параметры",
        "price_delta": "Отклонение цены",
        "size_fill_ratio": "Доля исполнения объема",
        "latency_delta_ms": "Отклонение задержки, мс",
        "actual_completion_reason": "Фактическая причина завершения",
        "confidence_outcome": "Итог по уверенности",
        "probability_outcome": "Итог по вероятности",
        "execution_outcome": "Итог по исполнению",
        "source_count_delta": "Изменение количества источников",
        "confidence_delta": "Изменение уверенности",
        "fair_probability_delta": "Изменение вероятности",
        "proposal_snapshot": "Снимок предложения",
        "fill_timestamp": "Время исполнения",
        "source": "Источник",
    }

    VALUE_LABELS = {
        "approved": "одобрено",
        "pending_manual_confirmation": "ожидает ручного подтверждения",
        "policy_rejected": "отклонено политиками",
        "rejected": "отклонено",
        "expired": "истекло",
        "cancelled": "отменено",
        "created": "создано",
        "prepared": "подготовлено",
        "blocked": "заблокировано",
        "superseded": "замещено",
        "submission_rejected": "отклонено на отправке",
        "submission_disabled": "отправка отключена",
        "submission_accepted": "отправка принята",
        "simulated_filled": "смоделировано: исполнено",
        "simulated_partial_fill": "смоделировано: частичное исполнение",
        "simulated_expired": "смоделировано: истекло",
        "simulated_cancelled": "смоделировано: отменено",
        "open": "открыт",
        "acknowledged": "подтвержден",
        "dismissed": "скрыт",
        "resolved": "решен",
        "proposal": "предложение",
        "market": "рынок",
        "intent": "намерение",
        "active": "активен",
        "closed": "закрыт",
        "outcomes": "итоги",
        "learning_summary": "обучающая сводка",
        "better_than_expected": "лучше ожиданий",
        "within_expected_range": "в пределах ожиданий",
        "worse_than_expected": "хуже ожиданий",
        "partially_filled": "частично исполнено",
        "confidence_held": "уверенность сохранилась",
        "confidence_degraded": "уверенность снизилась",
        "probability_moved_in_favor": "вероятность сдвинулась в пользу",
        "probability_moved_against": "вероятность сдвинулась против",
        "execution_favorable": "исполнение благоприятное",
        "execution_unfavorable": "исполнение неблагоприятное",
        "not_simulated": "не моделировалось",
        "proposal_ttl_nearing": "предложение близко к TTL",
        "approved_proposal_stale": "одобренное предложение устарело",
        "intent_superseded": "намерение замещено",
        "simulated_execution_recorded": "записано смоделированное исполнение",
        "warning": "предупреждение",
        "info": "инфо",
        "critical": "критично",
    }

    def __init__(self, services: OperatorDashboardServices) -> None:
        self.services = services

    def render_response(self, path: str, query_string: str = "") -> tuple[str, str]:
        query = parse_qs(query_string, keep_blank_values=False)
        try:
            status, body = self._route(path, query)
        except ValueError as exc:
            status = "404 Not Found"
            body = page(
                "Не найдено",
                hero("Интерфейс оператора", "Запрошенная сущность недоступна.")
                + panel("Ошибка поиска", f'<div class="empty">{escape(str(exc))}</div>'),
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
        if path.startswith("/markets/live/"):
            refresh = query.get("refresh", ["0"])[0] in {"1", "true", "yes"}
            return "200 OK", self._live_market_detail(path.rsplit("/", 1)[1], refresh=refresh)
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
            "Не найдено",
            hero("Интерфейс оператора", "Неизвестная страница") + panel("Маршрут не найден", '<div class="empty">Страница не найдена.</div>'),
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
                ("открытые алерты", len(open_alerts), "требуют внимания оператора"),
                ("активные предложения", len(active_proposals), "ожидают решения или уже одобрены"),
                ("активные намерения", len(active_intents), "созданы или подготовлены"),
                ("сохраненные виды", len(self.services.saved_view_service.list_all()), "переиспользуемые фильтры"),
            ]
        )
        body += '<div class="grid">'
        body += panel(
            "Открытые алерты",
            list_items(
                [self._alert_item(alert) for alert in open_alerts[:5]],
                "Нет открытых алертов.",
            )
            + link_row([("все алерты", "/alerts")]),
        )
        body += panel(
            "Активные предложения",
            list_items(
                [
                    self._status_item(
                        proposal.proposal_id,
                        proposal.status.value,
                        f"/proposals/{proposal.proposal_id}",
                        f"{proposal.market_title} | преимущество={proposal.edge:.4f} уверенность={proposal.confidence:.2f}",
                        tone="good" if proposal.status.value == "approved" else "warn",
                    )
                    for proposal in active_proposals[:5]
                ],
                "Нет активных предложений.",
            )
            + link_row([("все предложения", "/proposals?scope=active"), ("последнее одобренное", "/proposals/latest-approved")]),
        )
        body += panel(
            "Активные намерения",
            list_items(
                [
                    self._status_item(
                        intent.intent_id,
                        intent.status.value,
                        f"/intents/{intent.intent_id}",
                        f"предложение={intent.proposal_id} размер={intent.size_usd:.2f}",
                    )
                    for intent in active_intents[:5]
                ],
                "Нет активных намерений.",
            )
            + link_row([("все намерения", "/intents?scope=active"), ("последнее терминальное", "/intents/latest-terminal")]),
        )
        body += panel(
            "Последние разборы решений",
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
                "Разборов решений пока нет.",
            )
            + link_row([("разборы решений", "/decision-reviews")]),
        )
        body += panel(
            "Последний анализ итогов",
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
                "Снимков анализа пока нет.",
            )
            + link_row([("анализ", "/analysis"), ("сохраненные виды", "/views")]),
        )
        body += panel(
            "Последние оценки исполнения",
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
                "Оценок исполнения пока нет.",
            ),
        )
        body += panel(
            "Последняя симуляция",
            '<div class="empty">Смоделированных исполнений пока нет.</div>'
            if latest_simulation is None
            else self._kv(
                [
                    ("execution_id", latest_simulation.execution_id),
                    ("intent_id", latest_simulation.intent_id),
                    ("status", latest_simulation.status.value),
                    ("filled_size_usd", f"{latest_simulation.filled_size_usd:.2f}"),
                    ("completion_reason", latest_simulation.completion_reason or "-"),
                ]
            )
            + link_row([("карточка намерения", f"/intents/{latest_simulation.intent_id}")]),
        )
        body += panel(
            "Недавние алерты",
            list_items([self._alert_item(alert) for alert in recent_alerts], "Алертов пока нет.")
            + link_row([("очередь алертов", "/alerts")]),
        )
        body += "</div>"
        return shell_page(
            "Панель оператора",
            "Панель оператора",
            "Тонкий интерфейс поверх сохраненных сервисов и операторских сценариев.",
            body,
        )

    def _proposal_list(self, query: dict[str, list[str]]) -> str:
        scope = self._query_value(query, "scope", "all")
        proposals = self._filtered_proposals(scope)
        market_id = self._query_value(query, "market_id")
        if market_id is not None:
            proposals = [item for item in proposals if item.market_id == market_id]
        body = hero("Предложения", "Список и карточки, построенные на сервисе жизненного цикла предложений.")
        body += panel(
            "Список предложений",
            self._kv([("scope", scope), ("market_id", market_id or "-"), ("returned", len(proposals))])
            + link_row([("последнее одобренное", "/proposals/latest-approved"), ("сохраненные виды", "/views")])
            + list_items(
                [
                    self._status_item(
                        proposal.proposal_id,
                        proposal.status.value,
                        f"/proposals/{proposal.proposal_id}",
                        (
                            f"{proposal.market_title} | категория={proposal.market_category} "
                            f"уверенность={proposal.confidence:.2f} размер={proposal.current_size_usd:.2f}"
                        ),
                        tone="good" if proposal.status.value == "approved" else "warn",
                    )
                    for proposal in proposals
                ],
                "По фильтру ничего не найдено.",
            ),
        )
        return page("Предложения", body)

    def _proposal_detail(self, proposal_id: str) -> str:
        proposal = self.services.proposal_service.latest_proposal_state(proposal_id)
        alerts = self.services.notifications_service.list_alerts_for_entity(WatchTargetType.PROPOSAL, proposal_id)
        latest_review = self.services.decision_review_service.latest_persisted_for_proposal(proposal_id)
        body = hero("Карточка предложения", "Детальная страница на базе сервиса жизненного цикла предложений.")
        body += panel(
            proposal.proposal_id,
            self._kv(
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
            + chips(list(proposal.policy_decision.details.keys()), empty_message="нет деталей policy")
            + link_row(
                [
                    ("снимок исследования", f"/research/proposals/{proposal.proposal_id}"),
                    ("интегрированный разбор решения", f"/decision-reviews/proposals/{proposal.proposal_id}"),
                ]
            ),
            meta="Тонкая карточка; все изменения предложения остаются в сервисном слое.",
        )
        body += panel(
            "Тезисы и риски",
            chips(proposal.thesis, empty_message="нет тезисов")
            + chips(proposal.risks, empty_message="нет рисков"),
        )
        body += panel(
            "Алерты",
            list_items([self._alert_item(alert) for alert in alerts], "Для предложения нет алертов."),
        )
        if latest_review is not None:
            body += panel(
                "Последний разбор решения",
                self._kv(
                    [
                        ("review_id", latest_review.review_id),
                        ("confidence_outcome", latest_review.confidence_outcome),
                        ("probability_outcome", latest_review.probability_outcome),
                        ("execution_outcome", latest_review.execution_outcome),
                    ]
                )
                + link_row([("открыть разбор", f"/decision-reviews/proposals/{proposal.proposal_id}")]),
            )
        return page(f"Предложение {proposal.proposal_id}", body)

    def _latest_approved_proposal(self) -> str:
        proposal = self.services.proposal_service.latest_approved_proposal()
        body = hero("Последнее одобренное предложение", "Страница быстрого перехода к последнему одобренному предложению.")
        content = '<div class="empty">Нет одобренного предложения.</div>'
        if proposal is not None:
            content = self._kv(
                [
                    ("proposal_id", proposal.proposal_id),
                    ("market_title", proposal.market_title),
                    ("status", proposal.status.value),
                    ("updated_at", proposal.updated_at.isoformat()),
                ]
            ) + link_row(
                [
                    ("открыть карточку", f"/proposals/{proposal.proposal_id}"),
                    ("исследование", f"/research/proposals/{proposal.proposal_id}"),
                    ("разбор решения", f"/decision-reviews/proposals/{proposal.proposal_id}"),
                ]
            )
        body += panel("Последнее одобренное", content)
        return page("Последнее одобренное предложение", body)

    def _intent_list(self, query: dict[str, list[str]]) -> str:
        scope = self._query_value(query, "scope", "all")
        intents = self._filtered_intents(scope)
        proposal_id = self._query_value(query, "proposal_id")
        if proposal_id is not None:
            intents = [item for item in intents if item.proposal_id == proposal_id]
        body = hero("Намерения", "Тонкий интерфейс поверх сервисов списка и карточек execution pipeline.")
        body += panel(
            "Список намерений",
            self._kv([("scope", scope), ("proposal_id", proposal_id or "-"), ("returned", len(intents))])
            + link_row([("последнее терминальное", "/intents/latest-terminal"), ("сохраненные виды", "/views")])
            + list_items(
                [
                    self._status_item(
                        intent.intent_id,
                        intent.status.value,
                        f"/intents/{intent.intent_id}",
                        f"предложение={intent.proposal_id} размер={intent.size_usd:.2f} лимит={intent.limit_price:.4f}",
                    )
                    for intent in intents
                ],
                "По фильтру ничего не найдено.",
            ),
        )
        return page("Намерения", body)

    def _intent_detail(self, intent_id: str) -> str:
        intent = self.services.execution_service.latest_intent_state(intent_id)
        execution = self.services.execution_service.latest_simulated_execution(intent_id)
        evaluation = self.services.execution_evaluation_service.latest_persisted_for_intent(intent_id)
        timeline = self.services.execution_service.list_execution_timeline(intent_id)
        alerts = self.services.notifications_service.list_alerts_for_entity(WatchTargetType.INTENT, intent_id)
        body = hero("Карточка намерения", "Детальная страница на базе execution pipeline service.")
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
        body += panel(intent.intent_id, self._kv(rows) + link_row([("карточка предложения", f"/proposals/{intent.proposal_id}")]))
        if evaluation is not None:
            body += panel(
                "Последняя оценка исполнения",
                self._kv([("verdict", evaluation.verdict), ("summary", evaluation.summary)]),
            )
        body += panel(
            "Таймлайн",
            list_items(
                [
                    item_link(
                        self._display_value(event.event_type),
                        f"фрагмент={event.fragment_index} размер={event.size_usd:.2f}",
                        f"/intents/{intent_id}",
                        meta=f"цена={event.price:.4f} задержка_мс={event.latency_ms}",
                    )
                    for event in timeline
                ],
                "Нет событий моделируемого исполнения.",
            ),
        )
        body += panel("Алерты", list_items([self._alert_item(alert) for alert in alerts], "Для намерения нет алертов."))
        return page(f"Намерение {intent.intent_id}", body)

    def _latest_terminal_intent(self) -> str:
        intent = self.services.execution_service.latest_terminal_intent()
        body = hero("Последнее терминальное намерение", "Страница быстрого перехода к последнему терминальному намерению.")
        content = '<div class="empty">Нет терминального намерения.</div>'
        if intent is not None:
            content = self._kv(
                [
                    ("intent_id", intent.intent_id),
                    ("proposal_id", intent.proposal_id),
                    ("status", intent.status.value),
                    ("updated_at", intent.updated_at.isoformat()),
                ]
            ) + link_row([("открыть карточку", f"/intents/{intent.intent_id}"), ("предложение", f"/proposals/{intent.proposal_id}")])
        body += panel("Последнее терминальное", content)
        return page("Последнее терминальное намерение", body)

    def _alert_list(self, query: dict[str, list[str]]) -> str:
        state_value = self._query_value(query, "state")
        state = None if state_value is None else AlertState(state_value)
        watchlist_only = self._query_value(query, "watchlist_only", "0") == "1"
        alerts = self.services.notifications_service.list_alerts(watchlist_only=watchlist_only, state=state)
        entity_type = self._query_value(query, "entity_type")
        entity_id = self._query_value(query, "entity_id")
        if entity_type is not None and entity_id is not None:
            alerts = [alert for alert in alerts if alert.entity_type.value == entity_type and alert.entity_id == entity_id]
        body = hero("Алерты", "Список алертов с фильтрацией по состоянию и действиями жизненного цикла.")
        body += panel(
            "Список алертов",
            self._kv(
                [
                    ("state", state_value or "-"),
                    ("watchlist_only", watchlist_only),
                    ("entity", "-" if entity_id is None else f"{entity_type}:{entity_id}"),
                    ("returned", len(alerts)),
                ]
            )
            + list_items([self._alert_item(alert, include_actions=True) for alert in alerts], "По фильтру ничего не найдено."),
        )
        return page("Алерты", body)

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
        flash = f"Алерт {alert.alert_id} переведен в состояние «{self._display_value(alert.state.value)}»."
        body = panel(
            alert.alert_id,
            self._kv(
                [
                    ("alert_type", alert.alert_type.value),
                    ("state", alert.state.value),
                    ("entity", f"{alert.entity_type.value}:{alert.entity_id}"),
                    ("summary", alert.summary),
                ]
            )
            + link_row([("назад к списку", return_to), ("карточка сущности", self._entity_href(alert.entity_type.value, alert.entity_id))]),
        )
        return shell_page(
            "Алерт обновлен",
            "Алерт обновлен",
            "Переход состояния алерта выполнен через notification service.",
            body,
            flash=flash,
        )

    def _research_index(self, query: dict[str, list[str]]) -> str:
        proposal = self.services.proposal_service.latest_approved_proposal()
        market_id = self._query_value(query, "market_id")
        body = hero("Снимки исследования", "Последние probability и research views остаются read-only в интерфейсе.")
        body += panel(
            "Последнее исследование по предложению",
            '<div class="empty">Нет исследования для одобренного предложения.</div>'
            if proposal is None
            else self._kv([("proposal_id", proposal.proposal_id), ("market_id", proposal.market_id), ("market_title", proposal.market_title)])
            + link_row(
                [
                    ("снимок предложения", f"/research/proposals/{proposal.proposal_id}"),
                    ("интегрированный разбор решения", f"/decision-reviews/proposals/{proposal.proposal_id}"),
                    ("экспорт разбора решения", f"/exports/decision-reviews/proposals/{proposal.proposal_id}"),
                ]
            ),
        )
        body += panel(
            "Поиск по рынку",
            self._kv([("market_id", market_id or "-")])
            + (
                '<div class="empty">Передайте ?market_id=..., чтобы открыть снимок рынка.</div>'
                if market_id is None
                else link_row(
                    [
                    ("снимок рынка", f"/research/markets/{market_id}"),
                    ("live market", f"/markets/live/{market_id}"),
                    ("разбор решения по рынку", f"/decision-reviews/markets/{market_id}"),
                ]
            )
            ),
        )
        return page("Исследование", body)

    def _proposal_snapshot_detail(self, proposal_id: str) -> str:
        snapshot = self.services.proposal_service.latest_probability_snapshot_for_proposal(proposal_id)
        drift = self.services.proposal_service.compare_probability_snapshots_for_proposal(proposal_id)
        body = hero("Снимок предложения", "Детальная probability и research snapshot view.")
        body += panel(
            f"Снимок {snapshot.snapshot_id}",
            self._kv(
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
            + chips(snapshot.probability.key_factors, empty_message="нет ключевых факторов"),
        )
        body += panel(
            "Сводка исследования",
            self._kv(
                [
                    ("summary", snapshot.research_summary.summary),
                    ("source_count", snapshot.research_summary.source_count),
                    ("data_age_seconds", snapshot.data_age_seconds),
                    ("drift_summary", drift.drift_summary or "недостаточно истории"),
                ]
            )
            + chips(snapshot.research_summary.evidence_summary, empty_message="нет сводки по evidence"),
        )
        body += panel(
            "Источники и дрейф",
            chips(
                [f"{record.source_name}:{record.source_type.value}:{record.weight:.2f}" for record in snapshot.probability.evidence_records],
                empty_message="нет evidence records",
            )
            + chips(
                [f"{key}={value:+.4f}" for key, value in sorted(drift.source_type_contribution_deltas.items())],
                empty_message="нет изменений contribution по source type",
            ),
        )
        return page("Снимок предложения", body)

    def _market_snapshot_detail(self, market_id: str) -> str:
        snapshot = self.services.proposal_service.latest_probability_snapshot_for_market(market_id)
        drift = self.services.proposal_service.compare_probability_snapshots_for_market(market_id)
        body = hero("Снимок рынка", "Последний probability/research snapshot на уровне рынка.")
        body += panel(
            f"Рынок {snapshot.market_id}",
            self._kv(
                [
                    ("proposal_id", snapshot.proposal_id or "-"),
                    ("fair_probability", f"{snapshot.probability.fair_probability:.4f}"),
                    ("confidence", f"{snapshot.probability.confidence:.2f}"),
                    ("research_summary", snapshot.research_summary.summary),
                    ("drift_summary", drift.drift_summary or "недостаточно истории"),
                    ("created_at", snapshot.created_at.isoformat()),
                ]
            )
            + chips(snapshot.research_summary.evidence_summary, empty_message="нет сводки по evidence"),
        )
        body += panel("Live market data", link_row([("live snapshot", f"/markets/live/{market_id}")]))
        return page("Снимок рынка", body)

    def _live_market_detail(self, market_id: str, refresh: bool = False) -> str:
        if self.services.market_data_service is None:
            raise ValueError("Live market data service is not configured")
        snapshot = self.services.market_data_service.inspect_snapshot(market_id, refresh=refresh)
        cached = self.services.market_data_service.latest_cached_snapshot(market_id)
        body = hero("Рыночные live-данные", "Публичные metadata и CLOB pricing без включения live trading.")
        body += panel(
            f"Market {market_id}",
            self._kv(
                [
                    ("snapshot_id", snapshot.snapshot_id),
                    ("market_id", snapshot.market_id),
                    ("market_title", snapshot.market.title),
                    ("status", "active" if snapshot.market.active else "closed"),
                    ("source", snapshot.source),
                    ("data_age_seconds", snapshot.data_age_seconds),
                    ("current_price", f"{snapshot.orderbook.midpoint:.4f}"),
                    ("reference_price", "-" if snapshot.reference_price is None else f"{snapshot.reference_price:.4f}"),
                    ("observed_at", snapshot.observed_at.isoformat()),
                    ("stale", "yes" if snapshot.stale else "no"),
                    ("pricing_status", str(snapshot.pricing_metadata.get("price_status", "-"))),
                    ("created_at", snapshot.fetched_at.isoformat()),
                ]
            )
            + link_row(
                [
                    ("research snapshot", f"/research/markets/{market_id}"),
                    ("cached history", f"/research?market_id={market_id}"),
                    ("обновить сейчас", f"/markets/live/{market_id}?refresh=1"),
                ]
            ),
        )
        if cached is not None:
            body += panel(
                "Последний cached snapshot",
                self._kv(
                    [
                        ("snapshot_id", cached.snapshot_id),
                        ("source", cached.source),
                        ("data_age_seconds", cached.data_age_seconds),
                        ("best_bid", f"{cached.orderbook.best_bid:.4f}"),
                        ("best_ask", f"{cached.orderbook.best_ask:.4f}"),
                    ]
                ),
            )
        return page("Рыночные live-данные", body)

    def _decision_review_index(self, query: dict[str, list[str]]) -> str:
        proposal = self.services.proposal_service.latest_approved_proposal()
        market_id = self._query_value(query, "market_id")
        reviews = self.services.decision_review_service.list_recent(limit=10)
        body = hero("Разборы решений", "Интегрированный post-hoc context, собранный из сохраненных сервисов.")
        body += panel(
            "Поиск последнего разбора",
            '<div class="empty">Для одобренного предложения нет разбора решения.</div>'
            if proposal is None
            else self._kv([("proposal_id", proposal.proposal_id), ("market_id", proposal.market_id)])
            + link_row(
                [
                    ("последний разбор по одобренному", "/decision-reviews/proposals/latest-approved"),
                    ("разбор предложения", f"/decision-reviews/proposals/{proposal.proposal_id}"),
                ]
            ),
        )
        body += panel(
            "Поиск разбора по рынку",
            self._kv([("market_id", market_id or "-")])
            + (
                '<div class="empty">Передайте ?market_id=..., чтобы открыть разбор решения по рынку.</div>'
                if market_id is None
                else link_row([("разбор по рынку", f"/decision-reviews/markets/{market_id}")])
            ),
        )
        body += panel(
            "Недавние разборы решений",
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
                "Нет сохраненных разборов решений.",
            ),
        )
        return page("Разборы решений", body)

    def _latest_proposal_decision_review(self) -> str:
        proposal = self.services.proposal_service.latest_approved_proposal()
        body = hero("Последний разбор по предложению", "Быстрый переход к разбору последнего одобренного предложения.")
        if proposal is None:
            body += panel("Последний разбор", '<div class="empty">Нет одобренного предложения.</div>')
            return page("Последний разбор по предложению", body)
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
            "Разбор решения",
            hero("Разбор решения", "Интегрированный разбор предложения, исследования, дрейфа, намерения, исполнения и оценки.")
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
            "Разбор решения по рынку",
            hero("Разбор решения по рынку", "Интегрированный разбор на уровне рынка.")
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
        body = hero("Анализ итогов", "Групповой операторский анализ на основе сохраненных разборов и оценок.")
        body += panel(
            "Сводка анализа",
            self._kv(
                [
                    ("scope", snapshot.scope),
                    ("group_by", snapshot.group_by),
                    ("since_hours", snapshot.since_hours if snapshot.since_hours is not None else "-"),
                    ("summary", snapshot.summary),
                ]
            )
            + link_row(
                [
                    ("сохраненные виды", "/views"),
                    ("экспорт анализа", f"/exports/outcome-analysis?scope={snapshot.scope}&group_by={snapshot.group_by}"),
                ]
            ),
        )
        body += panel(
            "Группы",
            list_items(
                [
                    self._status_item(
                        group.group_value,
                        f"reviews={group.review_count} evaluations={group.evaluation_count}",
                        f"/analysis?scope={snapshot.scope}&group_by={snapshot.group_by}&latest=1",
                        (
                            f"уверенность сохранилась={group.confidence_held_count} "
                            f"уверенность снизилась={group.confidence_degraded_count} "
                            f"вердикты={self._localized_counts(group.verdict_counts)}"
                        ),
                        tone="good",
                    )
                    for group in snapshot.groups
                ],
                "Групповой анализ недоступен.",
            ),
        )
        return page("Анализ итогов", body)

    def _saved_view_list(self) -> str:
        views = self.services.saved_view_service.list_all()
        body = panel(
            "Список сохраненных видов",
            list_items(
                [
                    self._status_item(
                        saved.name,
                        saved.kind,
                        f"/views/{saved.name}",
                        f"параметры={saved.params}",
                        tone="good",
                    )
                    + link_row(
                        [
                            ("запустить", f"/views/{saved.name}/run"),
                            ("клонировать", f"/views/{saved.name}/clone?name={saved.name}-copy"),
                            ("редактировать", f"/views/{saved.name}/edit"),
                        ]
                    )
                    for saved in views
                ],
                "Сохраненных видов нет.",
            )
            + link_row(
                [
                    ("сохранить текущий фильтр предложений", "/views/save-current?name=active-proposals-ui&kind=proposals_list&scope=active"),
                    ("сохранить текущий фильтр анализа", "/views/save-current?name=market-analysis-ui&kind=analysis_outcomes&group_by=market"),
                ]
            ),
        )
        return shell_page(
            "Сохраненные виды",
            "Сохраненные виды",
            "Переиспользуемые фильтры и маршруты анализа на базе saved view service.",
            body,
        )

    def _saved_view_detail(self, name: str) -> str:
        saved = self.services.saved_view_service.get(name)
        if saved is None:
            raise ValueError(f"Unknown saved view: {name}")
        body = panel(
            saved.name,
            self._kv([("kind", saved.kind), ("created_at", saved.created_at.isoformat()), ("params", saved.params)])
            + link_row(
                [
                    ("запустить вид", f"/views/{saved.name}/run"),
                    ("клонировать", f"/views/{saved.name}/clone?name={saved.name}-copy"),
                    ("редактировать", f"/views/{saved.name}/edit"),
                    ("все сохраненные виды", "/views"),
                ]
            ),
        )
        return shell_page(
            f"Сохраненный вид {saved.name}",
            "Сохраненный вид",
            "Сохраненное определение фильтра для списков и сценариев анализа.",
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
            "Сохраненный вид клонирован",
            "Сохраненный вид клонирован",
            "Вид продублирован через saved view service.",
            panel(
                cloned.name,
                self._kv([("kind", cloned.kind), ("params", cloned.params)])
                + link_row([("открыть клон", f"/views/{cloned.name}"), ("запустить клон", f"/views/{cloned.name}/run")]),
            ),
            flash=f"Сохраненный вид {name} клонирован в {cloned.name}.",
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
            "Сохраненный вид обновлен",
            "Сохраненный вид обновлен",
            "Параметры вида обновлены через saved view service.",
            panel(
                updated.name,
                self._kv([("kind", updated.kind), ("params", updated.params)])
                + link_row([("открыть вид", f"/views/{updated.name}"), ("запустить вид", f"/views/{updated.name}/run"), ("все виды", "/views")]),
            ),
            flash=f"Сохраненный вид {name} обновлен.",
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
            "Текущий фильтр сохранен",
            "Текущий фильтр сохранен",
            "Текущий UI-фильтр сохранен через saved view service.",
            panel(
                saved.name,
                self._kv([("kind", saved.kind), ("params", saved.params)])
                + link_row([("открыть сохраненный вид", f"/views/{saved.name}"), ("запустить сохраненный вид", f"/views/{saved.name}/run")]),
            ),
            flash=f"Текущий фильтр сохранен как {saved.name}.",
        )

    def _export_decision_review(self, proposal_id: str) -> str:
        payload = self.services.reporting_service.export_decision_review(proposal_id)
        return shell_page(
            "Экспорт разбора решения",
            "Экспорт разбора решения",
            "Тонкий export view на базе reporting service.",
            panel(
                "Данные",
                json_block(json.dumps(payload, indent=2, sort_keys=True))
                + link_row([("назад к разбору", f"/decision-reviews/proposals/{proposal_id}")]),
            ),
        )

    def _export_execution_evaluation(self, proposal_id: str | None = None, intent_id: str | None = None) -> str:
        payload = self.services.reporting_service.export_execution_evaluation(proposal_id=proposal_id, intent_id=intent_id)
        back_href = f"/decision-reviews/proposals/{proposal_id}" if proposal_id is not None else f"/intents/{intent_id}"
        return shell_page(
            "Экспорт оценки исполнения",
            "Экспорт оценки исполнения",
            "Тонкий export view на базе reporting service.",
            panel(
                "Данные",
                json_block(json.dumps(payload, indent=2, sort_keys=True))
                + link_row([("назад", back_href)]),
            ),
        )

    def _export_outcome_analysis(self, query: dict[str, list[str]]) -> str:
        scope = self._query_value(query, "scope", "outcomes") or "outcomes"
        group_by = self._query_value(query, "group_by", "market") or "market"
        since_hours = self._query_int(query, "since_hours")
        payload = self.services.reporting_service.export_outcome_analysis(scope, group_by, since_hours)
        return shell_page(
            "Экспорт анализа итогов",
            "Экспорт анализа итогов",
            "Тонкий export view на базе reporting service.",
            panel(
                "Данные",
                json_block(json.dumps(payload, indent=2, sort_keys=True))
                + link_row([("назад к анализу", f"/analysis?scope={scope}&group_by={group_by}")]),
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
            "Обзор разбора",
            self._kv(
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
                    f"уверенность={self._display_value(outcomes.get('confidence', '-'))}",
                    f"вероятность={self._display_value(outcomes.get('probability', '-'))}",
                    f"исполнение={self._display_value(outcomes.get('execution', '-'))}",
                ]
            )
            + link_row(
                []
                if snapshot.proposal_id is None
                else [("экспорт разбора решения", f"/exports/decision-reviews/proposals/{snapshot.proposal_id}")]
            ),
        )
        body += panel(
            "Предложение",
            '<div class="empty">Предложение не привязано.</div>'
            if proposal is None
            else self._kv(
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
            "Снимок вероятности",
            self._kv(
                [
                    ("snapshot_id", probability_snapshot.get("snapshot_id", "-")),
                    ("fair_probability", probability_snapshot.get("fair_probability", "-")),
                    ("confidence", probability_snapshot.get("confidence", "-")),
                    ("source_count", probability_snapshot.get("source_count", "-")),
                    ("created_at", probability_snapshot.get("created_at", "-")),
                ]
            )
            + chips(probability_snapshot.get("key_factors", []), empty_message="нет ключевых факторов"),
        )
        body += panel(
            "Дрейф вероятности",
            self._kv(
                [
                    ("previous_snapshot_id", probability_drift.get("previous_snapshot_id", "-")),
                    ("fair_probability_delta", probability_drift.get("fair_probability_delta", "-")),
                    ("confidence_delta", probability_drift.get("confidence_delta", "-")),
                    ("source_count_delta", probability_drift.get("source_count_delta", "-")),
                    ("drift_summary", probability_drift.get("drift_summary", "-")),
                ]
            )
            + chips(probability_drift.get("added_key_factors", []), empty_message="нет добавленных факторов")
            + chips(probability_drift.get("removed_key_factors", []), empty_message="нет удаленных факторов"),
        )
        body += panel(
            "Намерение и исполнение",
            (
                '<div class="empty">Связанное намерение отсутствует.</div>'
                if intent is None
                else self._kv(
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
                '<div class="empty">Смоделированного исполнения нет.</div>'
                if execution is None
                else self._kv(
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
            "Оценка исполнения",
            '<div class="empty">Нет снимка оценки исполнения.</div>'
            if evaluation is None
            else self._kv(
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
                        "экспорт оценки",
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
            (
                f"{self._display_value(alert.alert_type.value)} | "
                f"серьезность={self._display_value(alert.severity.value)} | "
                f"сущность={self._display_value(alert.entity_type.value)}:{alert.entity_id}"
            ),
            tone=self._alert_tone(alert.state.value),
        )
        if not include_actions:
            return content
        actions = []
        if alert.state == AlertState.OPEN:
            actions.extend(
                [
                    ("подтвердить", f"/alerts/{alert.alert_id}/acknowledge?return_to={return_to}"),
                    ("скрыть", f"/alerts/{alert.alert_id}/dismiss?return_to={return_to}"),
                    ("решить", f"/alerts/{alert.alert_id}/resolve?return_to={return_to}"),
                ]
            )
        elif alert.state == AlertState.ACKNOWLEDGED:
            actions.extend(
                [
                    ("скрыть", f"/alerts/{alert.alert_id}/dismiss?return_to={return_to}"),
                    ("решить", f"/alerts/{alert.alert_id}/resolve?return_to={return_to}"),
                ]
            )
        return content + link_row(actions)

    def _status_item(self, title: str, status: str, href: str, meta: str, tone: str = "warn") -> str:
        display_status = self._display_value(status)
        return f"{badge(display_status, tone)} {item_link(title, display_status, href, meta=meta)}"

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

    def _kv(self, rows: list[tuple[str, object]]) -> str:
        return kv_table([(self.FIELD_LABELS.get(key, key), self._display_value(value)) for key, value in rows])

    def _display_value(self, value: object) -> object:
        if isinstance(value, bool):
            return "да" if value else "нет"
        if isinstance(value, str):
            return self.VALUE_LABELS.get(value, value)
        return value

    def _localized_counts(self, counts: dict[str, int]) -> dict[str, int]:
        return {str(self._display_value(key)): value for key, value in counts.items()}
