from __future__ import annotations

from bot.config.models import Settings
from bot.domain.enums import BotMode
from bot.adapters.polymarket.trading import ExecutionAdapter


class ManualExecutionGuard:
    def __init__(self, execution_adapter: ExecutionAdapter) -> None:
        self.execution_adapter = execution_adapter

    def ensure_manual_only(self) -> None:
        if self.execution_adapter.supports_live_execution:
            raise RuntimeError("semi_auto mode forbids autonomous live execution")


def guard_allows_live_execution(settings: Settings, execution_adapter: ExecutionAdapter) -> tuple[bool, str]:
    if settings.mode == BotMode.SEMI_AUTO:
        return False, "semi_auto guard forbids autonomous execution"
    if settings.mode in {BotMode.PAPER, BotMode.MANUAL_ONLY}:
        return False, f"{settings.mode.value} mode forbids live execution"
    if not execution_adapter.supports_live_execution:
        return False, "execution adapter does not support live submission"
    return False, "manual execution guard requires operator submission"
