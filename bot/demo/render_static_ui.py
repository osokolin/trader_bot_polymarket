from __future__ import annotations

from pathlib import Path

from bot.bootstrap import build_app_container_from_config
from bot.demo.seed import seed_demo_data


def render_static_ui_pages(output_dir: Path, config_dir: Path, profile: str = "balanced") -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    container = build_app_container_from_config(
        config_dir,
        profile,
        output_dir / "static_ui.db",
        include_market_runtime=False,
        include_telegram_runtime=False,
    )
    try:
        seeded = seed_demo_data(
            container.settings,
            container.proposal_service,
            container.execution_service,
            container.notifications_service,
            container.decision_review_service,
            container.execution_evaluation_service,
            container.outcome_analysis_service,
            container.saved_view_service,
        )
        app = container.dashboard_app()
        pages = {
            "ui-dashboard-home.html": app.render_response("/")[1],
            "ui-proposal-detail.html": app.render_response(f"/proposals/{seeded['approved_proposal_id']}")[1],
            "ui-decision-review.html": app.render_response(
                f"/decision-reviews/proposals/{seeded['approved_proposal_id']}"
            )[1],
            "ui-outcome-analysis.html": app.render_response("/analysis?scope=outcomes&group_by=market")[1],
        }
        for filename, html in pages.items():
            (output_dir / filename).write_text(html, encoding="utf-8")
        return {name: str(output_dir / name) for name in pages}
    finally:
        container.close()
