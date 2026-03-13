from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path

from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.config.loader import load_settings
from bot.services.analytics import AnalyticsService
from bot.services.audit_log import AuditLogService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.reporting import ReportingService
from bot.services.saved_views import SavedViewService
from bot.services.web_auth import WebAuthService
from bot.storage.db import Database
from bot.storage.repositories import (
    AlertRepository,
    AuditRepository,
    DecisionReviewRepository,
    ExecutionEvaluationRepository,
    OrderIntentRepository,
    OutcomeAnalysisRepository,
    ProbabilitySnapshotRepository,
    ProposalRepository,
    SavedViewRepository,
    WatchlistRepository,
    WebAuthRepository,
)
from bot.ui.app import AuthenticatedOperatorDashboardApp, OperatorDashboardServices


@dataclass(slots=True)
class WebResponse:
    status: str
    headers: list[tuple[str, str]]
    body: str


class WebUiClient:
    def __init__(self, app: AuthenticatedOperatorDashboardApp) -> None:
        self.app = app
        self.cookies: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        *,
        form_data: dict[str, str] | None = None,
        query_string: str = "",
        cookies: dict[str, str] | None = None,
    ) -> WebResponse:
        merged_cookies = dict(self.cookies)
        if cookies:
            merged_cookies.update(cookies)
        status, headers, body = self.app.render_http_response(
            method=method,
            path=path,
            query_string=query_string,
            form_data=form_data,
            cookies=merged_cookies,
            remote_addr="127.0.0.1",
            user_agent="test-agent",
        )
        self._apply_set_cookie_headers(headers)
        return WebResponse(status=status, headers=headers, body=body)

    def get(self, path: str, *, query_string: str = "", cookies: dict[str, str] | None = None) -> WebResponse:
        return self.request("GET", path, query_string=query_string, cookies=cookies)

    def post(self, path: str, *, form_data: dict[str, str], cookies: dict[str, str] | None = None) -> WebResponse:
        return self.request("POST", path, form_data=form_data, cookies=cookies)

    def _apply_set_cookie_headers(self, headers: list[tuple[str, str]]) -> None:
        for key, value in headers:
            if key != "Set-Cookie":
                continue
            parsed = SimpleCookie()
            parsed.load(value)
            for name, morsel in parsed.items():
                max_age = morsel["max-age"]
                if max_age == "0" or morsel.value == "":
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = morsel.value


class WebAuthUiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)

    def test_protected_route_requires_auth(self) -> None:
        with self._fixture() as fixture:
            response = fixture.client.get("/")
            self.assertEqual(response.status, "303 See Other")
            self.assertIn(("Location", "/login"), response.headers)

    def test_successful_login_creates_session(self) -> None:
        with self._fixture() as fixture:
            response = fixture.client.post(
                "/login",
                form_data={"username": "osokolin", "password": "Secret123!"},
            )
            self.assertEqual(response.status, "303 See Other")
            self.assertIn(("Location", "/"), response.headers)
            self.assertIn(WebAuthService.SESSION_COOKIE, fixture.client.cookies)

            home = fixture.client.get("/")
            self.assertEqual(home.status, "200 OK")
            self.assertIn("Панель оператора", home.body)

    def test_failed_login_returns_readable_error(self) -> None:
        with self._fixture() as fixture:
            response = fixture.client.post(
                "/login",
                form_data={"username": "osokolin", "password": "wrong-password"},
            )
            self.assertEqual(response.status, "401 Unauthorized")
            self.assertIn("Invalid username or password", response.body)

    def test_logout_revokes_session(self) -> None:
        with self._fixture() as fixture:
            fixture.client.post("/login", form_data={"username": "osokolin", "password": "Secret123!"})
            csrf_token = fixture.current_csrf_token()

            response = fixture.client.post("/logout", form_data={"csrf_token": csrf_token})
            self.assertEqual(response.status, "303 See Other")
            self.assertIn(("Location", "/login"), response.headers)
            self.assertNotIn(WebAuthService.SESSION_COOKIE, fixture.client.cookies)

            after = fixture.client.get("/")
            self.assertEqual(after.status, "303 See Other")
            self.assertIn(("Location", "/login"), after.headers)

    def test_remember_browser_restores_session(self) -> None:
        with self._fixture() as fixture:
            fixture.client.post(
                "/login",
                form_data={"username": "osokolin", "password": "Secret123!", "remember_browser": "1"},
            )
            remember_cookie = fixture.client.cookies[WebAuthService.REMEMBER_COOKIE]
            fixture.client.cookies.pop(WebAuthService.SESSION_COOKIE, None)

            response = fixture.client.get("/", cookies={WebAuthService.REMEMBER_COOKIE: remember_cookie})
            self.assertEqual(response.status, "200 OK")
            self.assertIn("Панель оператора", response.body)
            self.assertIn(WebAuthService.SESSION_COOKIE, fixture.client.cookies)
            self.assertIn(WebAuthService.REMEMBER_COOKIE, fixture.client.cookies)

    def test_revoked_remember_token_no_longer_works(self) -> None:
        with self._fixture() as fixture:
            fixture.client.post(
                "/login",
                form_data={"username": "osokolin", "password": "Secret123!", "remember_browser": "1"},
            )
            remember_cookie = fixture.client.cookies[WebAuthService.REMEMBER_COOKIE]
            csrf_token = fixture.current_csrf_token()
            fixture.client.post("/auth/revoke-remember", form_data={"csrf_token": csrf_token})

            fresh_client = WebUiClient(fixture.app)
            response = fresh_client.get("/", cookies={WebAuthService.REMEMBER_COOKIE: remember_cookie})
            self.assertEqual(response.status, "303 See Other")
            self.assertIn(("Location", "/login"), response.headers)

    def test_revoke_all_invalidates_active_auth(self) -> None:
        with self._fixture() as fixture:
            fixture.client.post(
                "/login",
                form_data={"username": "osokolin", "password": "Secret123!", "remember_browser": "1"},
            )
            session_cookie = fixture.client.cookies[WebAuthService.SESSION_COOKIE]
            remember_cookie = fixture.client.cookies[WebAuthService.REMEMBER_COOKIE]
            csrf_token = fixture.current_csrf_token()

            response = fixture.client.post("/auth/revoke-all", form_data={"csrf_token": csrf_token})
            self.assertEqual(response.status, "303 See Other")
            self.assertIn(("Location", "/login"), response.headers)

            fresh_client = WebUiClient(fixture.app)
            session_result = fresh_client.get("/", cookies={WebAuthService.SESSION_COOKIE: session_cookie})
            self.assertEqual(session_result.status, "303 See Other")
            remember_result = fresh_client.get("/", cookies={WebAuthService.REMEMBER_COOKIE: remember_cookie})
            self.assertEqual(remember_result.status, "303 See Other")

    def test_save_current_catalog_view_uses_post_and_preserves_multi_select_categories(self) -> None:
        with self._fixture() as fixture:
            fixture.client.post("/login", form_data={"username": "osokolin", "password": "Secret123!"})
            csrf_token = fixture.current_csrf_token()

            status, headers, body = fixture.app.render_http_response(
                method="POST",
                path="/views/save-current",
                form_data={
                    "name": "catalog-markets-default",
                    "kind": "markets_catalog",
                    "scope": "all",
                    "sort": "volume_desc",
                    "page_size": "20",
                    "category": "politics",
                    "csrf_token": csrf_token,
                },
                form_lists={
                    "name": ["catalog-markets-default"],
                    "kind": ["markets_catalog"],
                    "scope": ["all"],
                    "sort": ["volume_desc"],
                    "page_size": ["20"],
                    "category": ["crypto", "politics"],
                    "csrf_token": [csrf_token],
                },
                cookies=dict(fixture.client.cookies),
                remote_addr="127.0.0.1",
                user_agent="test-agent",
            )

            self.assertEqual(status, "200 OK")
            self.assertIn("Текущий фильтр сохранен", body)
            saved = fixture.app.services.saved_view_service.get("catalog-markets-default")
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.params["categories"], ["crypto", "politics"])
            self.assertEqual(saved.params["page_size"], 20)

    @dataclass(slots=True)
    class _Fixture:
        connection: object
        app: AuthenticatedOperatorDashboardApp
        client: WebUiClient
        auth_service: WebAuthService

        def current_csrf_token(self) -> str:
            session_cookie = self.client.cookies[WebAuthService.SESSION_COOKIE]
            session_id = session_cookie.split(".", 1)[0]
            session = self.auth_service.repository.get_session(session_id)
            assert session is not None
            return session.csrf_token

        def __enter__(self) -> "WebAuthUiTest._Fixture":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.connection.close()

    def _fixture(self) -> "WebAuthUiTest._Fixture":
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        database = Database(Path(tmp_dir.name) / "bot.db")
        database.initialize()
        connection = database.connect()

        proposal_repository = ProposalRepository(connection)
        intent_repository = OrderIntentRepository(connection)
        audit_log = AuditLogService(AuditRepository(connection))
        proposal_service = ProposalLifecycleService(
            proposal_repository,
            audit_log,
            ProposalEngine(),
            probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
        )
        notifications_service = OperatorNotificationsService(
            WatchlistRepository(connection),
            AlertRepository(connection),
            proposal_repository,
            intent_repository,
        )
        execution_service = ExecutionPipelineService(
            self.settings,
            SemiAutoExecutionAdapter(),
            intent_repository,
            audit_log,
            paper_execution_adapter=PaperExecutionAdapter(),
            notifications_service=notifications_service,
        )
        decision_review_service = DecisionReviewService(
            proposal_service,
            execution_service,
            DecisionReviewRepository(connection),
        )
        execution_evaluation_service = ExecutionEvaluationService(
            proposal_service,
            execution_service,
            ExecutionEvaluationRepository(connection),
        )
        outcome_analysis_service = OutcomeAnalysisService(
            proposal_service,
            DecisionReviewRepository(connection),
            ExecutionEvaluationRepository(connection),
            OutcomeAnalysisRepository(connection),
        )
        saved_view_service = SavedViewService(SavedViewRepository(connection))
        reporting_service = ReportingService(
            DecisionReviewRepository(connection),
            execution_evaluation_service,
            outcome_analysis_service,
            notifications_service,
            AnalyticsService(proposal_service, execution_service),
        )
        auth_service = WebAuthService(
            WebAuthRepository(connection),
            audit_log,
            cookie_secure=False,
        )
        auth_service.set_password("osokolin", "Secret123!")
        app = AuthenticatedOperatorDashboardApp(
            OperatorDashboardServices(
                proposal_service=proposal_service,
                execution_service=execution_service,
                notifications_service=notifications_service,
                decision_review_service=decision_review_service,
                execution_evaluation_service=execution_evaluation_service,
                outcome_analysis_service=outcome_analysis_service,
                saved_view_service=saved_view_service,
                reporting_service=reporting_service,
            ),
            auth_service,
        )
        return self._Fixture(connection=connection, app=app, client=WebUiClient(app), auth_service=auth_service)
