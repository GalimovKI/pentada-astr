"""Initial mail storage; no search index or benchmark labels."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("mailboxes",
        sa.Column("synthetic_user", sa.Text(collation="C"), primary_key=True))
    op.create_table("messages",
        sa.Column("doc_id", sa.Text(collation="C"), primary_key=True),
        sa.Column("synthetic_user", sa.Text(collation="C"),
                  sa.ForeignKey("mailboxes.synthetic_user"), nullable=False),
        sa.Column("doc", sa.Text, nullable=False),
        sa.Column("doc_dt", sa.Date))
    op.create_index("ix_messages_mailbox_date_id", "messages",
                    ["synthetic_user", sa.text("doc_dt DESC NULLS LAST"), "doc_id"])
    op.create_table("corpus_import",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.CheckConstraint("id = 1", name="singleton_import"),
        sa.Column("fingerprint", sa.Text, nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("mailboxes", sa.Integer, nullable=False),
        sa.Column("messages", sa.Integer, nullable=False),
        sa.Column("unknown_dates", sa.Integer, nullable=False),
        sa.Column("format_version", sa.Integer, nullable=False))


def downgrade():
    op.drop_table("corpus_import")
    op.drop_table("messages")
    op.drop_table("mailboxes")
