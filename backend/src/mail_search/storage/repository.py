"""Mailbox-scoped reads. NULL dates are available and sort last."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, func, or_, select

from ..domain.models import Document
from .schema import mailboxes, messages


class UnknownMailbox(LookupError):
    pass


@dataclass(frozen=True)
class MessagePreview:
    doc_id: str
    synthetic_user: str
    doc_dt: date | None
    snippet: str


@dataclass(frozen=True)
class MessageCursor:
    synthetic_user: str
    query_date: date | None
    doc_dt: date | None
    doc_id: str


@dataclass(frozen=True)
class MessagePage:
    items: tuple[MessagePreview, ...]
    next_cursor: MessageCursor | None


class MailStore:
    def __init__(self, engine):
        self.engine = engine

    def list_mailboxes(self):
        with self.engine.connect() as connection:
            return list(connection.scalars(select(mailboxes.c.synthetic_user)
                                            .order_by(mailboxes.c.synthetic_user)))

    @staticmethod
    def _scope(connection, synthetic_user, query_date):
        if connection.scalar(select(mailboxes.c.synthetic_user).where(
                mailboxes.c.synthetic_user == synthetic_user)) is None:
            raise UnknownMailbox(synthetic_user)
        filters = [messages.c.synthetic_user == synthetic_user]
        if query_date is not None:
            filters.append(or_(messages.c.doc_dt <= query_date, messages.c.doc_dt.is_(None)))
        return filters

    def list_messages(self, synthetic_user, *, query_date=None, limit=50, after=None):
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if after and (after.synthetic_user != synthetic_user or after.query_date != query_date):
            raise ValueError("Cursor belongs to a different mailbox or query_date")
        with self.engine.connect() as connection:
            filters = self._scope(connection, synthetic_user, query_date)
            if after:
                if after.doc_dt is None:
                    filters.append(and_(messages.c.doc_dt.is_(None), messages.c.doc_id > after.doc_id))
                else:
                    filters.append(or_(messages.c.doc_dt < after.doc_dt,
                        and_(messages.c.doc_dt == after.doc_dt, messages.c.doc_id > after.doc_id),
                        messages.c.doc_dt.is_(None)))
            rows = connection.execute(select(messages.c.doc_id, messages.c.synthetic_user,
                messages.c.doc_dt, func.left(messages.c.doc, 200).label("snippet"))
                .where(*filters).order_by(messages.c.doc_dt.desc().nulls_last(), messages.c.doc_id)
                .limit(limit + 1)).mappings().all()
        items = tuple(MessagePreview(**r) for r in rows[:limit])
        cursor = None
        if len(rows) > limit:
            last = items[-1]
            cursor = MessageCursor(synthetic_user, query_date, last.doc_dt, last.doc_id)
        return MessagePage(items, cursor)

    def get_message(self, synthetic_user, doc_id, *, query_date=None):
        result = self.get_messages(synthetic_user, [doc_id], query_date=query_date)
        return result[0] if result else None

    def get_messages(self, synthetic_user, doc_ids, *, query_date=None):
        """Missing, foreign and future IDs omitted; input order/duplicates preserved."""
        ids = list(doc_ids)
        with self.engine.connect() as connection:
            filters = self._scope(connection, synthetic_user, query_date)
            if not ids:
                return []
            rows = connection.execute(select(messages).where(
                *filters, messages.c.doc_id.in_(list(dict.fromkeys(ids))))).mappings()
            found = {r["doc_id"]: Document(**r) for r in rows}
        return [found[doc_id] for doc_id in ids if doc_id in found]

    def import_fingerprint(self):
        """A committed import row also probes DB/schema availability."""
        from .schema import corpus_import
        with self.engine.connect() as connection:
            row = connection.execute(select(corpus_import.c.fingerprint,
                                            corpus_import.c.format_version)).first()
            return row.fingerprint if row and row.format_version == 1 else None

    def get_previews(self, synthetic_user, doc_ids, *, query_date):
        """One scoped batch; full message bodies never leave PostgreSQL."""
        ids = list(doc_ids)
        with self.engine.connect() as connection:
            filters = self._scope(connection, synthetic_user, query_date)
            if not ids:
                return []
            rows = connection.execute(select(messages.c.doc_id, messages.c.synthetic_user,
                messages.c.doc_dt, func.left(messages.c.doc, 200).label("snippet"))
                .where(*filters, messages.c.doc_id.in_(ids))).mappings()
            found = {r["doc_id"]: MessagePreview(**r) for r in rows}
        return [found[did] for did in ids if did in found]
