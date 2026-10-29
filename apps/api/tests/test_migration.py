import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from deepstack.db import database_url


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_UNPOOLED"), reason="Needs direct test Postgres"
)
@pytest.mark.parametrize("existing", [False, True])
def test_migrations_preserve_empty_and_existing_databases(monkeypatch, existing):
    url = make_url(database_url(direct=True))
    schema = "deepstack_migration_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = url.update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", isolated.render_as_string(hide_password=False))
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        test_engine = create_engine(isolated)
        if existing:
            command.upgrade(config, "0001")
            with test_engine.begin() as conn:
                conn.execute(text("INSERT INTO guests VALUES ('legacy', now())"))
                conn.execute(
                    text(
                        "INSERT INTO game_sessions VALUES ('table', 'legacy', 'active', 7, jsonb_build_object('config', jsonb_build_object('players', 2)), now())"
                    )
                )
                conn.execute(
                    text("INSERT INTO hands VALUES ('hand', 'table', 1, '{}', '[]', now())")
                )
                conn.execute(
                    text(
                        "INSERT INTO opponent_memories VALUES ('legacy', 'mara', '{}', 'Keep this note')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO command_receipts VALUES ('legacy', 'command', 'table', 'hash', '{}')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO chip_ledger (session_id, seat, kind, amount, created_at) VALUES ('table', 0, 'buy_in', 60000, now())"
                    )
                )
        command.upgrade(config, "head")
        assert set(inspect(test_engine).get_table_names()) == {
            "alembic_version",
            "guests",
            "game_sessions",
            "opponent_memories",
            "hands",
            "command_receipts",
            "chip_ledger",
            "accounts",
        }
        if existing:
            with test_engine.connect() as conn:
                assert conn.execute(text("SELECT version, state FROM game_sessions")).one() == (
                    7,
                    {"config": {"players": 2}},
                )
                assert conn.execute(
                    text("SELECT decisions, bookmarked, note FROM hands")
                ).one() == ([], False, "")
                assert conn.scalar(text("SELECT note FROM opponent_memories")) == "Keep this note"
                assert conn.scalar(text("SELECT count(*) FROM command_receipts")) == 1
                assert conn.scalar(text("SELECT amount FROM chip_ledger")) == 60000
        test_engine.dispose()
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
