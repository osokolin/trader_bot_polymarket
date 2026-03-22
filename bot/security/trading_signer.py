from __future__ import annotations

import os
from collections.abc import Mapping

from bot.config.models import PolymarketGatewayConfig


class TradingSignerError(RuntimeError):
    """Raised when the trading signer is misconfigured or misused."""


def _normalize_secret(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class TradingSigner:
    """Isolated holder for Polymarket signing/auth credentials.

    This milestone keeps signing behind a narrow, injectable boundary. Live EIP-712
    signing is intentionally not enabled here yet; callers can inspect credential
    presence safely, but real signing attempts fail closed.
    """

    def __init__(
        self,
        *,
        private_key: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        api_passphrase: str | None = None,
    ) -> None:
        private_key = _normalize_secret(private_key)
        if private_key is not None and (not private_key.startswith("0x") or len(private_key) != 66):
            raise TradingSignerError("Trading signer private key format is invalid")
        self._private_key = private_key
        self._api_key = _normalize_secret(api_key)
        self._api_secret = _normalize_secret(api_secret)
        self._api_passphrase = _normalize_secret(api_passphrase)

    @classmethod
    def from_environment(cls, config: PolymarketGatewayConfig) -> "TradingSigner":
        return cls(
            private_key=os.getenv(config.private_key_env_var),
            api_key=os.getenv(config.api_key_env_var),
            api_secret=os.getenv(config.api_secret_env_var),
            api_passphrase=os.getenv(config.api_passphrase_env_var),
        )

    def __repr__(self) -> str:
        return (
            "TradingSigner("
            f"private_key={'set' if self._private_key else 'unset'}, "
            f"api_key={'set' if self._api_key else 'unset'}, "
            f"api_secret={'set' if self._api_secret else 'unset'}, "
            f"api_passphrase={'set' if self._api_passphrase else 'unset'})"
        )

    def credential_presence(self) -> dict[str, bool]:
        return {
            "private_key": self._private_key is not None,
            "api_key": self._api_key is not None,
            "api_secret": self._api_secret is not None,
            "api_passphrase": self._api_passphrase is not None,
        }

    def can_sign(self) -> bool:
        return self._private_key is not None

    def validate_for_live_submission(self) -> None:
        if self._private_key is None:
            raise TradingSignerError("Polymarket live submission requires a private key")
        if self._api_key is None or self._api_secret is None or self._api_passphrase is None:
            raise TradingSignerError("Polymarket live submission requires API key, secret, and passphrase")

    def sign_eip712_payload(self, payload: Mapping[str, object]) -> dict[str, object]:
        self.validate_for_live_submission()
        raise TradingSignerError(
            "Live EIP-712 signing is intentionally not enabled in this milestone"
        )
