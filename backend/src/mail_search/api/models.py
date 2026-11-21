import re
from datetime import date
from typing import Annotated
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def exact_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Expected YYYY-MM-DD")
    return date.fromisoformat(value)


ScenarioDate = Annotated[date, BeforeValidator(exact_date)]


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(strict=True, min_length=1, max_length=4000)
    query_date: ScenarioDate
    limit: int = Field(default=10, strict=True, ge=1, le=100)

    relevance_threshold: float | None = Field(default=None, strict=True, ge=-1, le=1, allow_inf_nan=False)
    min_similarity: float | None = Field(default=None, strict=True, ge=-1, le=1, allow_inf_nan=False)
    offset: int = Field(default=0, strict=True, ge=0)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Expected nonblank query")
        return value


class Preview(BaseModel):
    doc_id: str
    synthetic_user: str
    doc_dt: date | None
    snippet: str


class Message(BaseModel):
    doc_id: str
    synthetic_user: str
    doc_dt: date | None
    doc: str


class Passage(BaseModel):
    text: str
    offset: int
    ranges: list[tuple[int, int]]


class Hit(Preview):
    passage: Passage | None = None
    score: float


class MailboxGroup(BaseModel):
    id: str
    name: str
    items: list[str]


class Archive(BaseModel):
    id: str
    name: str
    mailbox: str
    total: int
    latest_date: date | None


class Mailboxes(BaseModel):
    archives: list[Archive] | None = None
    items: list[str]
    groups: list[MailboxGroup] | None = None


class Messages(BaseModel):
    total: int
    items: list[Preview]
    next_cursor: str | None


class MessageResponse(BaseModel):
    item: Message


class SearchResponse(BaseModel):
    total: int | None = None
    receipt_date: date | None = None
    items: list[Hit]


class Health(BaseModel):
    status: str


class ErrorDetail(BaseModel):
    code: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


def page_integer(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    if type(value) is int:
        return value
    raise ValueError("Expected integer")


PageLimit = Annotated[int, BeforeValidator(page_integer)]


class EvaluationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(max_length=64)
    dataset: str = Field(max_length=64)
