"""Accounts, recoverable guest ownership, and public decision review."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False, server_default="You"),
        sa.Column("preferences", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("table_defaults", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "guests",
        sa.Column("account_id", sa.String(128), sa.ForeignKey("accounts.id"), nullable=True),
    )
    op.create_index("ix_guests_account_id", "guests", ["account_id"])
    for column in (
        sa.Column("name", sa.String(32), nullable=False, server_default="You"),
        sa.Column("preferences", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("table_defaults", postgresql.JSONB(), nullable=False, server_default="{}"),
    ):
        op.add_column("guests", column)
    op.alter_column("opponent_memories", "profile", type_=sa.String(64))
    op.add_column(
        "hands", sa.Column("decisions", postgresql.JSONB(), nullable=False, server_default="[]")
    )
    op.add_column(
        "hands", sa.Column("bookmarked", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("hands", sa.Column("note", sa.Text(), nullable=False, server_default=""))
    op.create_index("ix_hands_created_id", "hands", ["created_at", "id"])


def downgrade():
    op.drop_index("ix_hands_created_id", table_name="hands")
    for name in ("note", "bookmarked", "decisions"):
        op.drop_column("hands", name)
    for name in ("table_defaults", "preferences", "name", "account_id"):
        op.drop_column("guests", name)
    op.drop_table("accounts")
