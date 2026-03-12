from __future__ import annotations

import hashlib
import hmac
import secrets
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

try:
    from argon2.exceptions import InvalidHashError
except ImportError:  # pragma: no cover - distro-packaged argon2 may expose InvalidHash instead
    from argon2.exceptions import InvalidHash as InvalidHashError

from bot.domain.models import RememberBrowserToken, WebSession, WebUser
from bot.services.audit_log import AuditLogService
from bot.storage.auth_repo import WebAuthRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class WebAuthError(ValueError):
    pass


@dataclass(slots=True)
class CookieInstruction:
    name: str
    value: str
    max_age: int | None = None
    expires: datetime | None = None
    http_only: bool = True
    secure: bool = True
    same_site: str = "Lax"
    path: str = "/"


@dataclass(slots=True)
class AuthenticatedWebRequest:
    user: WebUser
    session: WebSession
    csrf_token: str
    set_cookies: list[CookieInstruction]
    remember_token_id: str | None = None


@dataclass(slots=True)
class LoginResult:
    user: WebUser
    session: WebSession
    csrf_token: str
    set_cookies: list[CookieInstruction]


@dataclass(slots=True)
class WebAuthSecurityState:
    active_session_count: int
    active_remember_token_count: int


class WebAuthService:
    SESSION_COOKIE = "pm_ui_session"
    REMEMBER_COOKIE = "pm_ui_remember"
    USERNAME = "osokolin"

    def __init__(
        self,
        repository: WebAuthRepository,
        audit_log: AuditLogService,
        *,
        password_hasher: PasswordHasher | None = None,
        now_fn: Callable[[], datetime] = utc_now,
        session_ttl: timedelta = timedelta(hours=8),
        remember_ttl: timedelta = timedelta(days=30),
        cookie_secure: bool = True,
        max_failed_attempts: int = 5,
        lockout_window: timedelta = timedelta(minutes=15),
    ) -> None:
        self.repository = repository
        self.audit_log = audit_log
        self.password_hasher = password_hasher or PasswordHasher()
        self.now_fn = now_fn
        self.session_ttl = session_ttl
        self.remember_ttl = remember_ttl
        self.cookie_secure = cookie_secure
        self.max_failed_attempts = max_failed_attempts
        self.lockout_window = lockout_window
        self._failed_attempts: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)

    def set_password(self, username: str, password: str) -> WebUser:
        now = self.now_fn()
        existing = self.repository.get_user_by_username(username)
        user = WebUser(
            user_id=existing.user_id if existing is not None else new_id("user"),
            username=username,
            password_hash=self.password_hasher.hash(password),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self.repository.save_user(user)
        self.audit_log.log(
            "auth.password_updated",
            user.user_id,
            f"Password updated for {username}",
            {"source": "cli", "username": username},
        )
        return user

    def login(
        self,
        username: str,
        password: str,
        *,
        remote_addr: str,
        user_agent: str | None,
        remember_browser: bool,
    ) -> LoginResult:
        now = self.now_fn()
        if self._is_locked_out(username, remote_addr, now):
            raise WebAuthError("Too many failed login attempts. Please wait and try again.")
        user = self.repository.get_user_by_username(username)
        if user is None:
            self._record_failure(username, remote_addr, now, "unknown_user")
            raise WebAuthError("Invalid username or password.")
        try:
            if not self.password_hasher.verify(user.password_hash, password):
                raise WebAuthError("Invalid username or password.")
        except VerifyMismatchError:
            self._record_failure(username, remote_addr, now, "password_mismatch")
            raise WebAuthError("Invalid username or password.")
        except InvalidHashError as exc:
            self._record_failure(username, remote_addr, now, "invalid_hash")
            raise WebAuthError("Stored password hash is invalid.") from exc

        self._clear_failures(username, remote_addr)
        session, session_secret = self._new_session(user, remote_addr, user_agent, now)
        cookies = [
            self._cookie(
                self.SESSION_COOKIE,
                f"{session.session_id}.{session_secret}",
                max_age=int(self.session_ttl.total_seconds()),
            )
        ]
        if remember_browser:
            remember, remember_secret = self._new_remember_token(user, remote_addr, user_agent, now)
            cookies.append(
                self._cookie(
                    self.REMEMBER_COOKIE,
                    f"{remember.remember_token_id}.{remember_secret}",
                    max_age=int(self.remember_ttl.total_seconds()),
                )
            )
        self.audit_log.log(
            "auth.login_success",
            user.user_id,
            f"Successful login for {username}",
            {
                "source": "web",
                "username": username,
                "ip_address": remote_addr,
                "remember_browser": remember_browser,
            },
        )
        return LoginResult(user=user, session=session, csrf_token=session.csrf_token, set_cookies=cookies)

    def authenticate_request(
        self,
        *,
        session_cookie: str | None,
        remember_cookie: str | None,
        remote_addr: str,
        user_agent: str | None,
    ) -> AuthenticatedWebRequest | None:
        if session_cookie:
            authenticated = self._authenticate_session_cookie(session_cookie)
            if authenticated is not None:
                return AuthenticatedWebRequest(
                    user=authenticated[0],
                    session=authenticated[1],
                    csrf_token=authenticated[1].csrf_token,
                    set_cookies=[],
                )
        if not remember_cookie:
            return None
        return self._authenticate_remember_cookie(
            remember_cookie,
            remote_addr=remote_addr,
            user_agent=user_agent,
        )

    def logout(
        self,
        *,
        session_cookie: str | None,
        remember_cookie: str | None,
        remote_addr: str,
    ) -> list[CookieInstruction]:
        now = self.now_fn()
        user_id = None
        if session_cookie:
            parsed = self._parse_compound_cookie(session_cookie)
            if parsed is not None:
                session = self.repository.get_session(parsed[0])
                if session is not None:
                    user_id = session.user_id
                    self.repository.revoke_session(session.session_id, now)
        if remember_cookie:
            parsed = self._parse_compound_cookie(remember_cookie)
            if parsed is not None:
                remember = self.repository.get_remember_token(parsed[0])
                if remember is not None:
                    user_id = remember.user_id
                    self.repository.revoke_remember_token(remember.remember_token_id, now)
        if user_id is not None:
            self.audit_log.log(
                "auth.logout",
                user_id,
                "Web session logged out",
                {"source": "web", "ip_address": remote_addr},
            )
        return [self._delete_cookie(self.SESSION_COOKIE), self._delete_cookie(self.REMEMBER_COOKIE)]

    def revoke_current_remember_token(self, remember_cookie: str | None, *, actor_user: WebUser) -> list[CookieInstruction]:
        now = self.now_fn()
        if remember_cookie:
            parsed = self._parse_compound_cookie(remember_cookie)
            if parsed is not None:
                remember = self.repository.get_remember_token(parsed[0])
                if remember is not None:
                    self.repository.revoke_remember_token(remember.remember_token_id, now)
        self.audit_log.log(
            "auth.remember_revoked",
            actor_user.user_id,
            "Current remember-browser token revoked",
            {"source": "web", "username": actor_user.username},
        )
        return [self._delete_cookie(self.REMEMBER_COOKIE)]

    def revoke_all_auth(self, user: WebUser, *, remote_addr: str) -> list[CookieInstruction]:
        now = self.now_fn()
        self.repository.revoke_all_sessions_for_user(user.user_id, now)
        self.repository.revoke_all_remember_tokens_for_user(user.user_id, now)
        self.audit_log.log(
            "auth.revoke_all",
            user.user_id,
            "All active sessions and remember tokens revoked",
            {"source": "web", "username": user.username, "ip_address": remote_addr},
        )
        return [self._delete_cookie(self.SESSION_COOKIE), self._delete_cookie(self.REMEMBER_COOKIE)]

    def security_state(self, user: WebUser) -> WebAuthSecurityState:
        now = self.now_fn()
        return WebAuthSecurityState(
            active_session_count=self.repository.count_active_sessions(user.user_id, now),
            active_remember_token_count=self.repository.count_active_remember_tokens(user.user_id, now),
        )

    def verify_csrf(self, authenticated: AuthenticatedWebRequest, submitted_token: str | None) -> None:
        if not submitted_token or not hmac.compare_digest(authenticated.csrf_token, submitted_token):
            raise WebAuthError("Invalid or missing CSRF token.")

    def _authenticate_session_cookie(self, cookie_value: str) -> tuple[WebUser, WebSession] | None:
        parsed = self._parse_compound_cookie(cookie_value)
        if parsed is None:
            return None
        session_id, secret = parsed
        session = self.repository.get_session(session_id)
        now = self.now_fn()
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            return None
        if not hmac.compare_digest(session.token_hash, self._hash_token(secret)):
            return None
        user = self.repository.get_user(session.user_id)
        if user is None:
            return None
        return user, session

    def _authenticate_remember_cookie(
        self,
        cookie_value: str,
        *,
        remote_addr: str,
        user_agent: str | None,
    ) -> AuthenticatedWebRequest | None:
        parsed = self._parse_compound_cookie(cookie_value)
        if parsed is None:
            return None
        remember_token_id, secret = parsed
        remember = self.repository.get_remember_token(remember_token_id)
        now = self.now_fn()
        if remember is None or remember.revoked_at is not None or remember.expires_at <= now:
            return None
        if not hmac.compare_digest(remember.token_hash, self._hash_token(secret)):
            return None
        user = self.repository.get_user(remember.user_id)
        if user is None:
            return None
        self.repository.revoke_remember_token(remember.remember_token_id, now)
        session, session_secret = self._new_session(user, remote_addr, user_agent, now)
        rotated, rotated_secret = self._new_remember_token(user, remote_addr, user_agent, now)
        self.audit_log.log(
            "auth.remember_login",
            user.user_id,
            "Session restored from remember-browser token",
            {"source": "web", "username": user.username, "ip_address": remote_addr},
        )
        return AuthenticatedWebRequest(
            user=user,
            session=session,
            csrf_token=session.csrf_token,
            set_cookies=[
                self._cookie(
                    self.SESSION_COOKIE,
                    f"{session.session_id}.{session_secret}",
                    max_age=int(self.session_ttl.total_seconds()),
                ),
                self._cookie(
                    self.REMEMBER_COOKIE,
                    f"{rotated.remember_token_id}.{rotated_secret}",
                    max_age=int(self.remember_ttl.total_seconds()),
                ),
            ],
            remember_token_id=rotated.remember_token_id,
        )

    def _new_session(
        self,
        user: WebUser,
        remote_addr: str,
        user_agent: str | None,
        now: datetime,
    ) -> tuple[WebSession, str]:
        secret = secrets.token_urlsafe(32)
        session = WebSession(
            session_id=new_id("wsess"),
            user_id=user.user_id,
            token_hash=self._hash_token(secret),
            csrf_token=secrets.token_urlsafe(24),
            created_at=now,
            expires_at=now + self.session_ttl,
            last_seen_at=now,
            user_agent=user_agent,
            ip_address=remote_addr,
        )
        self.repository.save_session(session)
        return session, secret

    def _new_remember_token(
        self,
        user: WebUser,
        remote_addr: str,
        user_agent: str | None,
        now: datetime,
    ) -> tuple[RememberBrowserToken, str]:
        secret = secrets.token_urlsafe(32)
        token = RememberBrowserToken(
            remember_token_id=new_id("wrem"),
            user_id=user.user_id,
            token_hash=self._hash_token(secret),
            created_at=now,
            expires_at=now + self.remember_ttl,
            last_used_at=now,
            user_agent=user_agent,
            ip_address=remote_addr,
        )
        self.repository.save_remember_token(token)
        return token, secret

    def _is_locked_out(self, username: str, remote_addr: str, now: datetime) -> bool:
        attempts = self._failed_attempts[(username, remote_addr)]
        self._trim_attempts(attempts, now)
        return len(attempts) >= self.max_failed_attempts

    def _record_failure(self, username: str, remote_addr: str, now: datetime, reason: str) -> None:
        attempts = self._failed_attempts[(username, remote_addr)]
        self._trim_attempts(attempts, now)
        attempts.append(now)
        self.audit_log.log(
            "auth.login_failure",
            username,
            f"Failed login for {username}",
            {"source": "web", "username": username, "ip_address": remote_addr, "reason": reason},
        )

    def _clear_failures(self, username: str, remote_addr: str) -> None:
        self._failed_attempts.pop((username, remote_addr), None)

    def _trim_attempts(self, attempts: deque[datetime], now: datetime) -> None:
        cutoff = now - self.lockout_window
        while attempts and attempts[0] < cutoff:
            attempts.popleft()

    def _hash_token(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _parse_compound_cookie(self, value: str) -> tuple[str, str] | None:
        if "." not in value:
            return None
        item_id, secret = value.split(".", 1)
        if not item_id or not secret:
            return None
        return item_id, secret

    def _cookie(self, name: str, value: str, *, max_age: int) -> CookieInstruction:
        return CookieInstruction(
            name=name,
            value=value,
            max_age=max_age,
            http_only=True,
            secure=self.cookie_secure,
            same_site="Lax",
            path="/",
        )

    def _delete_cookie(self, name: str) -> CookieInstruction:
        return CookieInstruction(
            name=name,
            value="",
            max_age=0,
            expires=datetime(1970, 1, 1),
            http_only=True,
            secure=self.cookie_secure,
            same_site="Lax",
            path="/",
        )
