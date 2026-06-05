"""Shared test models, importable by both conftest fixtures and test files."""

import datetime

import pydantic


class Article(pydantic.BaseModel):
    title: str
    body: str | None = None
    views: int = 0
    rating: float = 0.0
    published: bool = False
    published_at: datetime.datetime | None = None
