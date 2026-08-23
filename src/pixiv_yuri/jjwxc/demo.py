"""Load the deterministic JJWXC demonstration catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pixiv_yuri.jjwxc.models import JjwxcNovel, JjwxcTrendPoint


class JjwxcDemoCatalog(BaseModel):
    """Validated fixture catalog for UI and API development."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_label: str = Field(min_length=1, max_length=80)
    novels: tuple[JjwxcNovel, ...] = Field(min_length=1, max_length=500)
    trends: tuple[JjwxcTrendPoint, ...] = Field(min_length=1, max_length=366)

    @model_validator(mode="after")
    def validate_catalog(self) -> JjwxcDemoCatalog:
        novel_ids = [item.novel_id for item in self.novels]
        if len(novel_ids) != len(set(novel_ids)):
            raise ValueError("duplicate fixture novel_id")
        days = [item.day for item in self.trends]
        if days != sorted(days) or len(days) != len(set(days)):
            raise ValueError("trend days must be unique and ascending")
        return self


@lru_cache(maxsize=1)
def load_demo_catalog() -> JjwxcDemoCatalog:
    """Read package data once and return a strict immutable catalog."""
    payload = (
        resources.files("pixiv_yuri.jjwxc")
        .joinpath("demo_catalog.json")
        .read_text(encoding="utf-8")
    )
    return JjwxcDemoCatalog.model_validate(json.loads(payload))
