import concurrent.futures
import hashlib
import json
import os
import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from deepstack import db
from main import COOKIE, app

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="Needs isolated Postgres"
)


def create(client, players=3):
    response = client.post(
        "/api/v1/sessions", json={"command_id": str(uuid4()), "config": {"players": players}}
    )
    assert response.status_code == 200, response.text
    return response.json()["snapshot"]


def command(client, s, kind, **fields):
    body = {"command_id": str(uuid4()), "expected_version": s["version"], "kind": kind, **fields}
    return client.post(f"/api/v1/sessions/{s['id']}/commands", json=body)


def finish(client, s):
    for _ in range(100):
        if s["complete"]:
            return s
        if s["needs_advance"]:
            response = command(client, s, "advance")
        else:
            kind = "check" if s["legal"]["check"] else "call"
            response = command(client, s, "act", action={"kind": kind})
        assert response.status_code == 200, response.text
        s = response.json()["snapshot"]
    raise AssertionError("API hand stuck")


def test_create_resume_idempotency_and_stale_versions(client):
    s = create(client)
    body = {"command_id": str(uuid4()), "expected_version": s["version"], "kind": "next_hand"}
    path = f"/api/v1/sessions/{s['id']}/commands"
    first = client.post(path, json=body)
    assert first.status_code == 200, first.text
    assert client.post(path, json=body).json() == first.json()
    conflicting = {**body, "kind": "advance"}
    assert client.post(path, json=conflicting).status_code == 409
    stale = {**body, "command_id": str(uuid4())}
    assert client.post(path, json=stale).status_code == 409
    db.factory.cache_clear()
    resumed = client.get(f"/api/v1/sessions/{s['id']}").json()
    assert resumed["snapshot"] == first.json()["snapshot"]


def test_concurrent_duplicate_taps_start_one_hand(client):
    s = create(client)
    body = {"command_id": str(uuid4()), "expected_version": 0, "kind": "next_hand"}
    cookies = dict(client.cookies)

    def submit(_):
        with TestClient(app) as second:
            return second.post(f"/api/v1/sessions/{s['id']}/commands", json=body, cookies=cookies)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert all(r.status_code == 200 for r in results)
    assert results[0].json() == results[1].json()
    assert results[0].json()["snapshot"]["hand_number"] == 1


def test_cross_guest_access_and_origin_rejected(client):
    s = create(client)
    with TestClient(app) as other:
        assert other.post("/api/v1/guest").status_code == 200
        other_id = hashlib.sha256(other.cookies[COOKIE].encode()).hexdigest()
        for suffix in ("", "/hands", "/ledger", "/hands/not-a-hand"):
            assert other.get(f"/api/v1/sessions/{s['id']}{suffix}").status_code == 404
        with db.factory()() as conn, conn.begin():
            conn.execute(delete(db.Guest).where(db.Guest.id == other_id))
    response = client.post(
        f"/api/v1/sessions/{s['id']}/commands",
        headers={"origin": "https://evil.example"},
        json={"command_id": str(uuid4()), "expected_version": 0, "kind": "next_hand"},
    )
    assert response.status_code == 403
    assert client.get(f"/api/v1/sessions/{s['id']}").json()["snapshot"]["version"] == 0


def test_cookie_flags_and_no_cache(client):
    response = client.post("/api/v1/guest", headers={"x-forwarded-proto": "https"})
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "private, no-store"


def test_history_replay_ledger_and_settlement_once(client):
    s = create(client)
    initial = command(client, s, "next_hand")
    assert initial.status_code == 200
    s = finish(client, initial.json()["snapshot"])
    hand_list = client.get(f"/api/v1/sessions/{s['id']}/hands").json()
    assert len(hand_list["hands"]) == 1
    hand = hand_list["hands"][0]
    replay = client.get(f"/api/v1/sessions/{s['id']}/hands/{hand['id']}").json()
    assert replay["events"][-1]["view"]["complete"]
    assert replay["events"][-1]["view"]["board"] == s["board"]
    assert s["profit"] == hand["profit"]
    with db.factory()() as conn:
        chips_in = conn.scalar(
            select(func.sum(db.Ledger.amount)).where(db.Ledger.session_id == s["id"])
        )
        assert sum(seat["stack"] for seat in s["seats"]) == chips_in
    again = command(client, s, "advance").json()["snapshot"]
    assert again["hands_played"] == 1 and again["profit"] == s["profit"]
    topped = command(client, again, "top_up", seat=0, amount=123).json()["snapshot"]
    assert topped["seats"][0]["stack"] == s["seats"][0]["stack"] + 123
    assert topped["profit"] == s["profit"]
    ended = command(client, topped, "end").json()["snapshot"]
    assert ended["cash_outs"] == topped["seats"][0]["stack"]
    with db.factory()() as conn:
        assert (
            conn.scalar(select(func.sum(db.Ledger.amount)).where(db.Ledger.session_id == s["id"]))
            == 0
        )
    assert client.get(f"/api/v1/sessions/{s['id']}/hands").json() == hand_list


def test_private_cards_and_deck_never_escape(client):
    s = create(client, 6)
    result = command(client, s, "next_hand").json()
    s = result["snapshot"]
    with db.factory()() as conn:
        private = conn.get(db.GameSession, s["id"]).state["hand"]
    allowed = set(s["board"] + private["hero_cards"])
    for cards in private["shown"].values():
        allowed.update(cards)
    strings = set(re.findall(r'"([2-9TJQKA][cdhs])"', json.dumps(result)))
    assert strings <= allowed
    assert not any(
        key in json.dumps(result)
        for key in ('"deck"', '"decision_seed"', '"profile"', '"commands"')
    )


def test_invalid_money_and_midhand_cashout_cannot_mutate(client):
    s = create(client, 2)
    s = command(client, s, "next_hand").json()["snapshot"]
    assert not s["complete"]
    assert command(client, s, "top_up", seat=0, amount=1.5).status_code == 422
    assert command(client, s, "end").status_code == 422
    assert client.get(f"/api/v1/sessions/{s['id']}").json()["snapshot"] == s
