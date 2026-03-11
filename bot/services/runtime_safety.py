from __future__ import annotations

from dataclasses import dataclass

from bot.adapters.polymarket.trading import ExecutionAdapter
from bot.config.models import Settings
from bot.domain.enums import BotMode
from bot.services.execution_guard import guard_allows_live_execution


@dataclass(slots=True)
class ExposureSummary:
    open_positions: int
    unresolved_exposure_usd: float
    unresolved_exposure_limit_usd: float
    unresolved_exposure_remaining_usd: float
    reserve_ratio: float
    total_bankroll_usd: float


@dataclass(slots=True)
class RuntimeSafetySnapshot:
    mode: BotMode
    profile: str
    kill_switch_enabled: bool
    manual_approval_required: bool
    auto_execute_disabled: bool
    config_live_execution_enabled: bool
    mode_supports_live_execution: bool
    adapter_supports_live_execution: bool
    guard_allows_live_execution: bool
    live_execution_enabled: bool
    live_execution_reason: str
    semi_auto_strict: bool
    exposure: ExposureSummary


def build_runtime_safety_snapshot(
    settings: Settings,
    profile: str,
    execution_adapter: ExecutionAdapter,
    open_positions: int,
    unresolved_exposure_usd: float,
) -> RuntimeSafetySnapshot:
    unresolved_limit = settings.bankroll.total_usd * settings.position_limits.max_unresolved_exposure_pct
    config_live_execution_enabled = not settings.approvals.auto_execute_disabled
    mode_supports_live_execution = settings.mode in {BotMode.LIVE_SMALL, BotMode.LIVE_FULL}
    adapter_supports_live_execution = execution_adapter.supports_live_execution
    guard_enabled, guard_reason = guard_allows_live_execution(settings, execution_adapter)
    live_execution_enabled = (
        config_live_execution_enabled
        and mode_supports_live_execution
        and adapter_supports_live_execution
        and guard_enabled
    )
    if live_execution_enabled:
        live_execution_reason = "config, mode, adapter, and guard all allow live execution"
    elif not config_live_execution_enabled:
        live_execution_reason = "config disables live execution"
    elif not mode_supports_live_execution:
        live_execution_reason = f"mode {settings.mode.value} does not allow live execution"
    elif not adapter_supports_live_execution:
        live_execution_reason = "execution adapter does not support live submission"
    else:
        live_execution_reason = guard_reason
    return RuntimeSafetySnapshot(
        mode=settings.mode,
        profile=profile,
        kill_switch_enabled=settings.safety.kill_switch_enabled,
        manual_approval_required=settings.approvals.manual_approval_required,
        auto_execute_disabled=settings.approvals.auto_execute_disabled,
        config_live_execution_enabled=config_live_execution_enabled,
        mode_supports_live_execution=mode_supports_live_execution,
        adapter_supports_live_execution=adapter_supports_live_execution,
        guard_allows_live_execution=guard_enabled,
        live_execution_enabled=live_execution_enabled,
        live_execution_reason=live_execution_reason,
        semi_auto_strict=(
            settings.mode == BotMode.SEMI_AUTO
            and settings.approvals.manual_approval_required
            and settings.approvals.auto_execute_disabled
        ),
        exposure=ExposureSummary(
            open_positions=open_positions,
            unresolved_exposure_usd=unresolved_exposure_usd,
            unresolved_exposure_limit_usd=unresolved_limit,
            unresolved_exposure_remaining_usd=max(0.0, unresolved_limit - unresolved_exposure_usd),
            reserve_ratio=settings.bankroll.reserve_ratio,
            total_bankroll_usd=settings.bankroll.total_usd,
        ),
    )
