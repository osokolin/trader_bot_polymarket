"""Optional external integration boundaries."""

from bot.integrations.polymarket_gateway import (
    PolymarketGateway,
    PolymarketGatewayConfigError,
    PolymarketGatewayOrder,
    PolymarketGatewayOrderBook,
    PolymarketGatewayOrderReceipt,
    PolymarketGatewayQuote,
)

__all__ = [
    "PolymarketGateway",
    "PolymarketGatewayConfigError",
    "PolymarketGatewayOrder",
    "PolymarketGatewayOrderBook",
    "PolymarketGatewayOrderReceipt",
    "PolymarketGatewayQuote",
]
