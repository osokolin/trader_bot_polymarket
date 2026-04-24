from __future__ import annotations

from bot.services.signals.engine import SignalEvaluation, StrategyDiagnosticsSnapshot


def strategy_diagnostics_lines(snapshot: StrategyDiagnosticsSnapshot) -> list[str]:
    lines = [
        "strategy_diagnostics",
        f"enabled={snapshot.enabled}",
        f"legacy_bidirectional_enabled={snapshot.legacy_bidirectional_enabled}",
        f"auto_execute_disabled={snapshot.auto_execute_disabled}",
        f"enabled_strategies={','.join(snapshot.enabled_strategies) or '-'}",
        f"disabled_strategies={','.join(snapshot.disabled_strategies) or '-'}",
        f"min_confidence={snapshot.min_confidence:.4f}",
        f"max_spread_bps={snapshot.max_spread_bps:.2f}",
        f"min_liquidity_usd={snapshot.min_liquidity_usd:.2f}",
        f"min_time_to_resolution_seconds={snapshot.min_time_to_resolution_seconds}",
        f"max_position_fraction={snapshot.max_position_fraction:.4f}",
        f"last_evaluated={snapshot.last_evaluated_count}",
        f"last_accepted={snapshot.last_accepted_count}",
        f"last_rejected={snapshot.last_rejected_count}",
    ]
    if snapshot.last_rejection_counts:
        rejection_str = ",".join(
            f"{code}={count}" for code, count in sorted(snapshot.last_rejection_counts.items())
        )
        lines.append(f"last_rejection_counts={rejection_str}")
    return lines


def strategy_evaluation_lines(evaluation: SignalEvaluation) -> list[str]:
    lines = [
        "strategy_evaluation",
        f"evaluated={evaluation.evaluated_count}",
        f"accepted={len(evaluation.accepted)}",
        f"rejected={len(evaluation.rejected)}",
    ]
    for decision in evaluation.accepted:
        signal = decision.signal
        lines.append(
            f"accepted type={signal.signal_type.value} "
            f"direction={signal.direction.value} "
            f"confidence={decision.confidence:.4f} "
            f"size_fraction={decision.proposed_size_fraction:.4f} "
            f"reason={decision.reason}"
        )
    for decision in evaluation.rejected:
        signal = decision.signal
        lines.append(
            f"rejected type={signal.signal_type.value} "
            f"direction={signal.direction.value} "
            f"confidence={decision.confidence:.4f} "
            f"code={decision.rejection_code or '-'} "
            f"reason={decision.reason}"
        )
    return lines
