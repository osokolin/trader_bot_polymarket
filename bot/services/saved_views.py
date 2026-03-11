from __future__ import annotations

from bot.domain.models import SavedView
from bot.storage.repositories import SavedViewRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class SavedViewService:
    SCHEMAS: dict[str, dict[str, object]] = {
        "proposals_list": {
            "required": {"scope"},
            "optional": {"limit", "offset", "sort"},
            "validators": {
                "scope": lambda value: value in {"all", "active", "approved"},
                "limit": lambda value: isinstance(value, int) and value >= 0,
                "offset": lambda value: isinstance(value, int) and value >= 0,
                "sort": lambda value: value in {"updated_desc", "updated_asc", "created_desc", "created_asc", "status"},
            },
        },
        "intents_list": {
            "required": {"scope"},
            "optional": {"limit", "offset", "sort"},
            "validators": {
                "scope": lambda value: value in {"all", "active", "terminal"},
                "limit": lambda value: isinstance(value, int) and value >= 0,
                "offset": lambda value: isinstance(value, int) and value >= 0,
                "sort": lambda value: value in {"updated_desc", "updated_asc", "created_desc", "created_asc", "status"},
            },
        },
        "alerts_list": {
            "required": set(),
            "optional": {"watchlist_only", "state"},
            "validators": {
                "watchlist_only": lambda value: isinstance(value, bool),
                "state": lambda value: value in {"open", "acknowledged", "dismissed", "resolved"},
            },
        },
        "analysis_outcomes": {
            "required": {"group_by"},
            "optional": {"since_hours"},
            "validators": {
                "group_by": lambda value: value in {"market", "category", "source_type", "confidence_band", "verdict_type"},
                "since_hours": lambda value: isinstance(value, int) and value >= 0,
            },
        },
        "analysis_learning": {
            "required": {"group_by"},
            "optional": {"since_hours"},
            "validators": {
                "group_by": lambda value: value in {"market", "category", "source_type", "confidence_band", "verdict_type"},
                "since_hours": lambda value: isinstance(value, int) and value >= 0,
            },
        },
    }

    def __init__(self, repository: SavedViewRepository) -> None:
        self.repository = repository

    def save(self, name: str, kind: str, params: dict[str, object]) -> SavedView:
        self._validate(kind, params)
        saved_view = SavedView(
            view_id=new_id("view"),
            name=name,
            kind=kind,
            params=params,
            created_at=utc_now(),
        )
        self.repository.save(saved_view)
        return saved_view

    def get(self, name: str) -> SavedView | None:
        return self.repository.get_by_name(name)

    def list_all(self) -> list[SavedView]:
        return self.repository.list_all()

    def _validate(self, kind: str, params: dict[str, object]) -> None:
        schema = self.SCHEMAS.get(kind)
        if schema is None:
            raise ValueError(f"Unsupported saved view kind: {kind}")
        required = schema["required"]
        optional = schema["optional"]
        validators = schema["validators"]
        provided = set(params)
        missing = required - provided
        if missing:
            raise ValueError(f"Missing saved view params: {', '.join(sorted(missing))}")
        unknown = provided - required - optional
        if unknown:
            raise ValueError(f"Unknown saved view params: {', '.join(sorted(unknown))}")
        for key, value in params.items():
            validator = validators.get(key)
            if validator is not None and not validator(value):
                raise ValueError(f"Invalid saved view param: {key}={value!r}")
