from __future__ import annotations


class PolymarketAdapterError(RuntimeError):
    pass


class PolymarketTransportError(PolymarketAdapterError):
    pass


class PolymarketHTTPError(PolymarketAdapterError):
    pass


class PolymarketParseError(PolymarketAdapterError):
    pass


class PolymarketStaleDataError(PolymarketAdapterError):
    pass


class PolymarketWebSocketError(PolymarketAdapterError):
    pass
