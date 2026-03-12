from __future__ import annotations


PROPOSAL_ACTIONS = {"approve", "reject", "cancel", "analysis", "details"}
REQUEST_ACTIONS = {"approve", "reject", "cancel", "analysis", "details", "acknowledge", "refresh"}


def proposal_callback(action: str, proposal_id: str) -> str:
    if action not in PROPOSAL_ACTIONS:
        raise ValueError(f"Unknown proposal action: {action}")
    return f"proposal:{action}:{proposal_id}"


def parse_callback(data: str) -> tuple[str, str] | None:
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "proposal":
        return None
    action, proposal_id = parts[1], parts[2]
    if action not in PROPOSAL_ACTIONS or not proposal_id:
        return None
    return action, proposal_id


def request_callback(action: str, request_id: str) -> str:
    if action not in REQUEST_ACTIONS:
        raise ValueError(f"Unknown request action: {action}")
    return f"request:{action}:{request_id}"


def parse_request_callback(data: str) -> tuple[str, str] | None:
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "request":
        return None
    action, request_id = parts[1], parts[2]
    if action not in REQUEST_ACTIONS or not request_id:
        return None
    return action, request_id
