import base64
import json
from pydantic import BaseModel, ConfigDict, Field
from .models import ScenarioDate
from ..core.datasets import PUBLIC_DATASET
from ..storage.repository import MessageCursor
from ..application.mail import ServiceError


class CursorData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    v: int = Field(ge=1, le=1)
    dataset: str = PUBLIC_DATASET
    synthetic_user: str
    query_date: ScenarioDate
    doc_dt: ScenarioDate | None
    doc_id: str = Field(min_length=1, max_length=1000)


def encode(cursor, dataset=PUBLIC_DATASET):
    if cursor is None:
        return None
    data = dict(v=1, synthetic_user=cursor.synthetic_user, query_date=cursor.query_date.isoformat(),
                doc_dt=cursor.doc_dt.isoformat() if cursor.doc_dt else None, doc_id=cursor.doc_id)
    if dataset != PUBLIC_DATASET:
        data["dataset"] = dataset
    return base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False).encode()).decode().rstrip("=")


def decode(value, user, query_date, dataset=PUBLIC_DATASET):
    if value is None:
        return None
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        data = CursorData.model_validate(json.loads(raw))
        if data.dataset != dataset or data.synthetic_user != user or data.query_date != query_date or (data.doc_dt and data.doc_dt > query_date):
            raise ValueError
        return MessageCursor(data.synthetic_user, data.query_date, data.doc_dt, data.doc_id)
    except Exception:
        raise ServiceError(422, "invalid_cursor") from None
