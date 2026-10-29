import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool

load_dotenv(Path(__file__).resolve().parents[3] / ".env.local")


class Base(DeclarativeBase):
    pass


def now():
    return datetime.now(UTC)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), default="You")
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    table_defaults: Mapped[dict] = mapped_column(JSONB, default=dict)


class Guest(Base):
    __tablename__ = "guests"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(32), default="You")
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    table_defaults: Mapped[dict] = mapped_column(JSONB, default=dict)


class GameSession(Base):
    __tablename__ = "game_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guest_id: Mapped[str] = mapped_column(ForeignKey("guests.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="active")
    version: Mapped[int] = mapped_column(BigInteger, default=0)
    state: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index(
            "one_active_session",
            "guest_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class Memory(Base):
    __tablename__ = "opponent_memories"
    guest_id: Mapped[str] = mapped_column(ForeignKey("guests.id"), primary_key=True)
    profile: Mapped[str] = mapped_column(String(64), primary_key=True)
    observed: Mapped[dict] = mapped_column(JSONB)
    note: Mapped[str] = mapped_column(Text, default="")


class Hand(Base):
    __tablename__ = "hands"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("game_sessions.id"), index=True)
    number: Mapped[int] = mapped_column(BigInteger)
    summary: Mapped[dict] = mapped_column(JSONB)
    events: Mapped[list] = mapped_column(JSONB)
    decisions: Mapped[list] = mapped_column(JSONB, default=list)
    bookmarked: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("session_hand_number", "session_id", "number", unique=True),)


class Receipt(Base):
    __tablename__ = "command_receipts"
    guest_id: Mapped[str] = mapped_column(ForeignKey("guests.id"), primary_key=True)
    command_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)


class Ledger(Base):
    __tablename__ = "chip_ledger"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("game_sessions.id"), index=True)
    seat: Mapped[int]
    kind: Mapped[str] = mapped_column(String(12))
    amount: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def database_url(direct=False):
    raw = os.environ.get("DATABASE_URL_UNPOOLED" if direct else "DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is not configured.")
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://") :]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


@lru_cache(maxsize=1)
def factory():
    engine = create_engine(database_url(), poolclass=NullPool, connect_args={"connect_timeout": 10})
    return sessionmaker(engine, expire_on_commit=False)
