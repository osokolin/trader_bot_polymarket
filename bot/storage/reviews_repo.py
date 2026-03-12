from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from bot.domain.decisions import PolicyDecision
from bot.domain.enums import (
    AlertState,
    AlertSeverity,
    AlertType,
    IntentStatus,
    OperatorActionEntityType,
    OperatorActionRequestStatus,
    OperatorActionRequestType,
    PolicyRejectionReason,
    ProposalStatus,
    SourceType,
    TradeAction,
    WatchTargetType,
)
from bot.domain.models import (
    AuditEvent,
    DecisionReviewSnapshot,
    EvidenceRecord,
    ExecutionEvaluationSnapshot,
    Market,
    MarketDataSnapshot,
    OutcomeAnalysisGroup,
    OutcomeAnalysisSnapshot,
    OrderBookSnapshot,
    OperatorActionRequest,
    OperatorActionRequestRecord,
    ProbabilitySnapshot,
    ProbabilityEstimate,
    ResearchSummary,
    OperatorAlert,
    OrderIntent,
    Position,
    SavedView,
    SimulatedFillEvent,
    SimulatedExecution,
    SimulationSummary,
    TradeProposal,
    WatchlistEntry,
)

class ProbabilitySnapshotRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, snapshot: ProbabilitySnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO probability_snapshots (
                snapshot_id, market_id, proposal_id, fair_probability, confidence, model_agreement,
                trusted_source_present, source_types_json, key_factors_json, source_count,
                confidence_components_json, explanation, source_inputs_json, evidence_records_json,
                source_type_contributions_json, research_summary, research_key_factors_json,
                thesis_points_json, risk_points_json, evidence_summary_json, current_price,
                data_age_seconds, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.market_id,
                snapshot.proposal_id,
                snapshot.probability.fair_probability,
                snapshot.probability.confidence,
                snapshot.probability.model_agreement,
                int(snapshot.probability.trusted_source_present),
                json.dumps([item.value for item in snapshot.probability.source_types]),
                json.dumps(snapshot.probability.key_factors),
                snapshot.probability.source_count,
                json.dumps(snapshot.probability.confidence_components),
                snapshot.probability.explanation,
                json.dumps(snapshot.probability.source_inputs),
                json.dumps(
                    [
                        {
                            "source_id": item.source_id,
                            "source_name": item.source_name,
                            "source_type": item.source_type.value,
                            "weight": item.weight,
                            "contribution": item.contribution,
                            "summary": item.summary,
                            "supports_trade": item.supports_trade,
                        }
                        for item in snapshot.probability.evidence_records
                    ]
                ),
                json.dumps(snapshot.probability.source_type_contributions, sort_keys=True),
                snapshot.research_summary.summary,
                json.dumps(snapshot.research_summary.key_factors),
                json.dumps(snapshot.research_summary.thesis_points),
                json.dumps(snapshot.research_summary.risk_points),
                json.dumps(snapshot.research_summary.evidence_summary),
                snapshot.current_price,
                snapshot.data_age_seconds,
                snapshot.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest_for_proposal(self, proposal_id: str) -> ProbabilitySnapshot | None:
        items = self.list_for_proposal(proposal_id, limit=1)
        return items[0] if items else None

    def latest_for_market(self, market_id: str) -> ProbabilitySnapshot | None:
        items = self.list_for_market(market_id, limit=1)
        return items[0] if items else None

    def list_for_proposal(self, proposal_id: str, limit: int | None = None) -> list[ProbabilitySnapshot]:
        sql = """
            SELECT * FROM probability_snapshots
            WHERE proposal_id = ?
            ORDER BY created_at DESC
        """
        params: tuple[object, ...] = (proposal_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (proposal_id, limit)
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def list_for_market(self, market_id: str, limit: int | None = None) -> list[ProbabilitySnapshot]:
        sql = """
            SELECT * FROM probability_snapshots
            WHERE market_id = ?
            ORDER BY created_at DESC
        """
        params: tuple[object, ...] = (market_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (market_id, limit)
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> ProbabilitySnapshot:
        probability = ProbabilityEstimate(
            market_id=row["market_id"],
            fair_probability=row["fair_probability"],
            confidence=row["confidence"],
            model_agreement=row["model_agreement"],
            trusted_source_present=bool(row["trusted_source_present"]),
            source_types=[SourceType(item) for item in json.loads(row["source_types_json"])],
            key_factors=json.loads(row["key_factors_json"]),
            source_count=row["source_count"],
            confidence_components=json.loads(row["confidence_components_json"]),
            explanation=row["explanation"],
            source_inputs=json.loads(row["source_inputs_json"]),
            evidence_records=[
                EvidenceRecord(
                    source_id=item["source_id"],
                    source_name=item["source_name"],
                    source_type=SourceType(item["source_type"]),
                    weight=item["weight"],
                    contribution=item["contribution"],
                    summary=item["summary"],
                    supports_trade=item.get("supports_trade", True),
                )
                for item in json.loads(row["evidence_records_json"])
            ],
            source_type_contributions=json.loads(row["source_type_contributions_json"]),
        )
        research = ResearchSummary(
            market_id=row["market_id"],
            proposal_id=row["proposal_id"],
            summary=row["research_summary"],
            key_factors=json.loads(row["research_key_factors_json"]),
            thesis_points=json.loads(row["thesis_points_json"]),
            risk_points=json.loads(row["risk_points_json"]),
            source_count=row["source_count"],
            evidence_summary=json.loads(row["evidence_summary_json"]),
        )
        return ProbabilitySnapshot(
            snapshot_id=row["snapshot_id"],
            market_id=row["market_id"],
            proposal_id=row["proposal_id"],
            probability=probability,
            research_summary=research,
            current_price=row["current_price"],
            data_age_seconds=row["data_age_seconds"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class DecisionReviewRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, review: DecisionReviewSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO decision_reviews (
                review_id, scope, market_id, proposal_id, probability_snapshot_id, previous_snapshot_id,
                intent_id, execution_id, confidence_outcome, probability_outcome, execution_outcome,
                summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review.review_id,
                review.scope,
                review.market_id,
                review.proposal_id,
                review.probability_snapshot_id,
                review.previous_snapshot_id,
                review.intent_id,
                review.execution_id,
                review.confidence_outcome,
                review.probability_outcome,
                review.execution_outcome,
                review.summary,
                json.dumps(review.payload),
                review.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest_for_proposal(self, proposal_id: str) -> DecisionReviewSnapshot | None:
        rows = self.connection.execute(
            """
            SELECT * FROM decision_reviews
            WHERE proposal_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (proposal_id,),
        ).fetchone()
        return None if rows is None else self._row_to_snapshot(rows)

    def latest_for_market(self, market_id: str) -> DecisionReviewSnapshot | None:
        rows = self.connection.execute(
            """
            SELECT * FROM decision_reviews
            WHERE market_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (market_id,),
        ).fetchone()
        return None if rows is None else self._row_to_snapshot(rows)

    def list_all(self) -> list[DecisionReviewSnapshot]:
        rows = self.connection.execute(
            """
            SELECT * FROM decision_reviews
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> DecisionReviewSnapshot:
        return DecisionReviewSnapshot(
            review_id=row["review_id"],
            scope=row["scope"],
            market_id=row["market_id"],
            proposal_id=row["proposal_id"],
            probability_snapshot_id=row["probability_snapshot_id"],
            previous_snapshot_id=row["previous_snapshot_id"],
            intent_id=row["intent_id"],
            execution_id=row["execution_id"],
            confidence_outcome=row["confidence_outcome"],
            probability_outcome=row["probability_outcome"],
            execution_outcome=row["execution_outcome"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class ExecutionEvaluationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, evaluation: ExecutionEvaluationSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO execution_evaluations (
                evaluation_id, proposal_id, intent_id, execution_id, verdict, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation.evaluation_id,
                evaluation.proposal_id,
                evaluation.intent_id,
                evaluation.execution_id,
                evaluation.verdict,
                evaluation.summary,
                json.dumps(evaluation.payload),
                evaluation.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest_for_intent(self, intent_id: str) -> ExecutionEvaluationSnapshot | None:
        row = self.connection.execute(
            """
            SELECT * FROM execution_evaluations
            WHERE intent_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (intent_id,),
        ).fetchone()
        return None if row is None else self._row_to_snapshot(row)

    def latest_for_proposal(self, proposal_id: str) -> ExecutionEvaluationSnapshot | None:
        row = self.connection.execute(
            """
            SELECT * FROM execution_evaluations
            WHERE proposal_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (proposal_id,),
        ).fetchone()
        return None if row is None else self._row_to_snapshot(row)

    def list_all(self) -> list[ExecutionEvaluationSnapshot]:
        rows = self.connection.execute(
            """
            SELECT * FROM execution_evaluations
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> ExecutionEvaluationSnapshot:
        return ExecutionEvaluationSnapshot(
            evaluation_id=row["evaluation_id"],
            proposal_id=row["proposal_id"],
            intent_id=row["intent_id"],
            execution_id=row["execution_id"],
            verdict=row["verdict"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class OutcomeAnalysisRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, snapshot: OutcomeAnalysisSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO outcome_analysis_snapshots (
                snapshot_id, scope, group_by, since_hours, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.scope,
                snapshot.group_by,
                snapshot.since_hours,
                snapshot.summary,
                json.dumps(
                    {
                        "groups": [
                            {
                                "group_by": item.group_by,
                                "group_value": item.group_value,
                                "review_count": item.review_count,
                                "evaluation_count": item.evaluation_count,
                                "average_fair_probability_delta": item.average_fair_probability_delta,
                                "average_confidence_delta": item.average_confidence_delta,
                                "confidence_held_count": item.confidence_held_count,
                                "confidence_degraded_count": item.confidence_degraded_count,
                                "probability_in_favor_count": item.probability_in_favor_count,
                                "probability_against_count": item.probability_against_count,
                                "execution_favorable_count": item.execution_favorable_count,
                                "execution_unfavorable_count": item.execution_unfavorable_count,
                                "verdict_counts": item.verdict_counts,
                            }
                            for item in snapshot.groups
                        ]
                    }
                ),
                snapshot.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest(self, scope: str, group_by: str) -> OutcomeAnalysisSnapshot | None:
        row = self.connection.execute(
            """
            SELECT * FROM outcome_analysis_snapshots
            WHERE scope = ? AND group_by = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (scope, group_by),
        ).fetchone()
        return None if row is None else self._row_to_snapshot(row)

    def list_all(self) -> list[OutcomeAnalysisSnapshot]:
        rows = self.connection.execute(
            """
            SELECT * FROM outcome_analysis_snapshots
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> OutcomeAnalysisSnapshot:
        payload = json.loads(row["payload_json"])
        return OutcomeAnalysisSnapshot(
            snapshot_id=row["snapshot_id"],
            scope=row["scope"],
            group_by=row["group_by"],
            since_hours=row["since_hours"],
            groups=[
                OutcomeAnalysisGroup(
                    group_by=item["group_by"],
                    group_value=item["group_value"],
                    review_count=item["review_count"],
                    evaluation_count=item["evaluation_count"],
                    average_fair_probability_delta=item["average_fair_probability_delta"],
                    average_confidence_delta=item["average_confidence_delta"],
                    confidence_held_count=item["confidence_held_count"],
                    confidence_degraded_count=item["confidence_degraded_count"],
                    probability_in_favor_count=item["probability_in_favor_count"],
                    probability_against_count=item["probability_against_count"],
                    execution_favorable_count=item["execution_favorable_count"],
                    execution_unfavorable_count=item["execution_unfavorable_count"],
                    verdict_counts=item["verdict_counts"],
                )
                for item in payload["groups"]
            ],
            summary=row["summary"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
