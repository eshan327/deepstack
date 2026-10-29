import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from deepstack import db
from main import COOKIE, app


@pytest.fixture
def client():
    with TestClient(app) as client:
        assert client.post("/api/v1/guest").status_code == 200
        tokens = {client.cookies[COOKIE]}
        yield client
        if client.cookies.get(COOKIE):
            tokens.add(client.cookies[COOKIE])
    guests = [hashlib.sha256(token.encode()).hexdigest() for token in tokens]
    with db.factory()() as conn, conn.begin():
        sids = select(db.GameSession.id).where(db.GameSession.guest_id.in_(guests))
        conn.execute(delete(db.Receipt).where(db.Receipt.guest_id.in_(guests)))
        conn.execute(delete(db.Ledger).where(db.Ledger.session_id.in_(sids)))
        conn.execute(delete(db.Hand).where(db.Hand.session_id.in_(sids)))
        conn.execute(delete(db.GameSession).where(db.GameSession.guest_id.in_(guests)))
        conn.execute(delete(db.Memory).where(db.Memory.guest_id.in_(guests)))
        conn.execute(delete(db.Guest).where(db.Guest.id.in_(guests)))
