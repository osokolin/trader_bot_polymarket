from __future__ import annotations

from wsgiref.simple_server import make_server

from bot.ui.app import OperatorDashboardApp


def serve_ui(app: OperatorDashboardApp, host: str, port: int) -> None:
    with make_server(host, port, app) as server:
        print(f"operator ui serving on http://{host}:{port}")
        server.serve_forever()
