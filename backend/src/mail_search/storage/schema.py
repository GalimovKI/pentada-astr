"""SQL schema, separate from the domain dataclasses; created only by Alembic."""
import sqlalchemy as sa

metadata = sa.MetaData()
mailboxes = sa.Table("mailboxes", metadata,
    sa.Column("synthetic_user", sa.Text(collation="C"), primary_key=True))
messages = sa.Table("messages", metadata,
    sa.Column("doc_id", sa.Text(collation="C"), primary_key=True),
    sa.Column("synthetic_user", sa.Text(collation="C"),
              sa.ForeignKey("mailboxes.synthetic_user"), nullable=False),
    sa.Column("doc", sa.Text, nullable=False),
    sa.Column("doc_dt", sa.Date))
sa.Index("ix_messages_mailbox_date_id", messages.c.synthetic_user,
         messages.c.doc_dt.desc().nulls_last(), messages.c.doc_id)
corpus_import = sa.Table("corpus_import", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.CheckConstraint("id = 1", name="singleton_import"),
    sa.Column("fingerprint", sa.Text, nullable=False),
    sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False,
              server_default=sa.func.now()),
    sa.Column("mailboxes", sa.Integer, nullable=False),
    sa.Column("messages", sa.Integer, nullable=False),
    sa.Column("unknown_dates", sa.Integer, nullable=False),
    sa.Column("format_version", sa.Integer, nullable=False))
