from __future__ import annotations


PROPOSAL_ACTIONS = {"approve", "reject", "cancel", "analysis", "details"}


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
