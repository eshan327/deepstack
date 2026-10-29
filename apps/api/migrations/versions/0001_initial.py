"""Guest tables, private state, safe history, receipts, observations, and chip ledger."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "guests",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "command_receipts",
        sa.Column("guest_id", sa.String(length=64), nullable=False),
        sa.Column("command_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["guest_id"],
            ["guests.id"],
        ),
        sa.PrimaryKeyConstraint("guest_id", "command_id"),
    )
    op.create_table(
        "game_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("guest_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["guest_id"],
            ["guests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_game_sessions_guest_id"), "game_sessions", ["guest_id"], unique=False)
    op.create_index(
        "one_active_session",
        "game_sessions",
        ["guest_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "opponent_memories",
        sa.Column("guest_id", sa.String(length=64), nullable=False),
        sa.Column("profile", sa.String(length=24), nullable=False),
        sa.Column("observed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guest_id"],
            ["guests.id"],
        ),
        sa.PrimaryKeyConstraint("guest_id", "profile"),
    )
    op.create_table(
        "chip_ledger",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chip_ledger_session_id"), "chip_ledger", ["session_id"], unique=False)
    op.create_table(
        "hands",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hands_session_id"), "hands", ["session_id"], unique=False)
    op.create_index("session_hand_number", "hands", ["session_id", "number"], unique=True)


def downgrade():
    op.drop_table("hands")
    op.drop_table("chip_ledger")
    op.drop_table("opponent_memories")
    op.drop_table("game_sessions")
    op.drop_table("command_receipts")
    op.drop_table("guests")
