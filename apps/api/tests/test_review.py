import copy
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from sqlalchemy import delete, select
from starlette.requests import Request

from deepstack import auth, db, engine, session
from deepstack.analysis import analyze
from deepstack.schemas import Action, AnalysisRequest, DecisionContext, LegalActions, TableConfig
from tests.test_api import command, create, finish
from tests.test_engine import act, table


def context(cards=("As", "Ah"), board=("Ac", "Ad", "2h", "3h", "4h"), side=False):
    t = session.new_table("review", TableConfig(players=2))
    public = engine.view(t)
    public.board = list(board)
    public.pot = 3000
    for seat in public.seats:
        seat.in_hand = True
    public.seats[0].cards = list(cards)
    public.actor = 0
    return DecisionContext(
        event_id=1,
        view=public,
        legal=LegalActions(call=1000),
        effective_stack=10000,
        action=Action(kind="call"),
        side_pots=side,
    )


def test_analysis_known_winner_tie_and_call_price():
    result = analyze(context(), AnalysisRequest(decision=0, ranges={1: "KhKd"}))
    assert result.equity == 1 and result.samples == 512
    assert result.call_threshold == 0.25 and result.uncertainty > 0
    tied = analyze(
        context(("2s", "3s"), ("Ah", "Kh", "Qh", "Jh", "Th")),
        AnalysisRequest(decision=0, ranges={1: "4s5s"}),
    )
    assert tied.equity == 0.5
    side = analyze(context(side=True), AnalysisRequest(decision=0, ranges={1: "KhKd"}))
    assert side.call_threshold is None and "Side-pot" in side.explanation


@pytest.mark.parametrize("raw", ["AsAh", "not a range", "", "Ac", "????", "AsAs"])
def test_analysis_rejects_conflicting_or_invalid_ranges(raw):
    with pytest.raises(ValueError):
        analyze(context(), AnalysisRequest(decision=0, ranges={1: raw}))


def test_analysis_only_reads_decision_information():
    decision = context(("As", "Qs"), ("Qh", "8s", "3d"))
    frozen = decision.model_dump_json()
    first = analyze(decision, AnalysisRequest(decision=0, ranges={1: "77+,AJs+,KQs,AQo+"}))
    second = analyze(
        copy.deepcopy(decision), AnalysisRequest(decision=0, ranges={1: "77+,AJs+,KQs,AQo+"})
    )
    assert first == second
    assert frozen == decision.model_dump_json()
    with pytest.raises(ValueError, match="active"):
        analyze(decision, AnalysisRequest(decision=0, ranges={2: "KK"}))


def test_multiway_equity_rejects_cross_range_conflicts_and_splits_ties():
    decision = context(("2s", "3s"), ("Ah", "Kh", "Qh", "Jh", "Th"))
    third = decision.view.seats[1].model_copy(update={"seat": 2, "name": "Third"})
    decision.view.seats.append(third)
    result = analyze(decision, AnalysisRequest(decision=0, ranges={1: "4s5s", 2: "6s7s"}))
    assert result.equity == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="compatible"):
        analyze(decision, AnalysisRequest(decision=0, ranges={1: "4s5s", 2: "4s5s"}))


def test_names_are_distinct_and_memories_do_not_follow_bot_profiles():
    t = session.new_table("names", TableConfig(players=9), {"mara": {"note": "old opponent"}})
    assert len({s["name"] for s in t["seats"][1:]}) == 8
    assert len({s["opponent_id"] for s in t["seats"]}) == 9
    assert all(not s["note"] for s in t["seats"])
    original = copy.deepcopy(t["seats"])
    session.start_hand(t, 42)
    assert [s["name"] for s in t["seats"]] == [s["name"] for s in original]


def test_events_distinguish_blinds_bets_raises_and_incremental_amounts():
    t, state = table(2)
    blind = next(e for e in t["hand"]["events"] if e.get("action") == "blind")
    assert "Blind" in blind["text"]
    act(t, state, "raise_to", 60)
    event = next(e for e in reversed(t["hand"]["events"]) if e.get("action") == "raise")
    assert event["to_amount"] == 60 and event["amount"] == 50
    act(t, state, "call")
    act(t, state, "raise_to", 40)
    event = next(e for e in reversed(t["hand"]["events"]) if e.get("action") == "bet")
    assert "Bet" in event["text"] and event["amount"] == 40 and event["street"] == "Flop"


def test_jwt_verifies_signature_claims_and_expiry(monkeypatch):
    from time import time

    private = Ed25519PrivateKey.generate()
    monkeypatch.setenv("NEON_AUTH_BASE_URL", "https://auth.example.test/db/auth")
    monkeypatch.setattr(
        auth,
        "keys",
        lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key())
        ),
    )
    payload = {
        "sub": "test-user",
        "role": "authenticated",
        "iat": int(time()),
        "exp": int(time()) + 900,
        "iss": "https://auth.example.test",
        "aud": "https://auth.example.test",
    }

    def request(data, key=private):
        token = jwt.encode(data, key, algorithm="EdDSA")
        return Request(
            {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}
        )

    assert auth.identity(request(payload))["sub"] == "test-user"
    for field, value in (
        ("exp", int(time()) - 60),
        ("iss", "https://wrong.test"),
        ("aud", "wrong"),
        ("role", "anonymous"),
        ("banned", True),
    ):
        with pytest.raises(HTTPException) as caught:
            auth.identity(request({**payload, field: value}))
        assert caught.value.status_code == 401
    with pytest.raises(HTTPException):
        auth.identity(request(payload, Ed25519PrivateKey.generate()))


@pytest.fixture
def identities(client, monkeypatch):
    import main

    subjects = {f"test-{uuid4()}", f"test-{uuid4()}"}

    def identity(request):
        header = request.headers.get("authorization")
        if not header:
            return None
        subject = header.removeprefix("Bearer ")
        if subject not in subjects:
            raise HTTPException(401, "Invalid identity")
        return {"sub": subject, "name": "Player", "role": "authenticated"}

    monkeypatch.setattr(main.auth, "identity", identity)
    yield tuple(subjects)
    client.headers.pop("Authorization", None)
    with db.factory()() as conn, conn.begin():
        guests = select(db.Guest.id).where(db.Guest.account_id.in_(subjects))
        sessions = select(db.GameSession.id).where(db.GameSession.guest_id.in_(guests))
        conn.execute(delete(db.Receipt).where(db.Receipt.guest_id.in_(guests)))
        conn.execute(delete(db.Ledger).where(db.Ledger.session_id.in_(sessions)))
        conn.execute(delete(db.Hand).where(db.Hand.session_id.in_(sessions)))
        conn.execute(delete(db.GameSession).where(db.GameSession.guest_id.in_(guests)))
        conn.execute(delete(db.Memory).where(db.Memory.guest_id.in_(guests)))
        conn.execute(delete(db.Guest).where(db.Guest.id.in_(guests)))
        conn.execute(delete(db.Account).where(db.Account.id.in_(subjects)))


db_test = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="Needs isolated Postgres")


@db_test
def test_claim_preserves_tables_and_blocks_signed_out_cookie(client, identities):
    alice, bob = identities
    guest_table = create(client)
    client.headers["Authorization"] = f"Bearer {alice}"
    account_table = create(client)
    assert client.post("/api/v1/me/claim", json={}).status_code == 200
    assert client.post("/api/v1/me/claim", json={}).status_code == 200
    assert {s["id"] for s in client.get("/api/v1/sessions").json()["sessions"]} == {
        guest_table["id"],
        account_table["id"],
    }
    client.headers["Authorization"] = f"Bearer {bob}"
    assert client.get(f"/api/v1/sessions/{guest_table['id']}").status_code == 404
    assert client.post("/api/v1/me/claim", json={}).status_code == 409
    client.headers.pop("Authorization")
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.post("/api/v1/guest/reset", json={}).status_code == 200
    assert client.get("/api/v1/sessions").json()["sessions"] == []


@db_test
def test_review_annotations_exports_and_decisions_are_owned(client, identities):
    alice, bob = identities
    client.headers["Authorization"] = f"Bearer {alice}"
    s = create(client)
    s = finish(client, command(client, s, "next_hand").json()["snapshot"])
    hand = client.get("/api/v1/hands").json()["hands"][0]
    replay = client.get(f"/api/v1/hands/{hand['id']}").json()
    assert replay["decisions"]
    assert all(not seat["cards"] for d in replay["decisions"] for seat in d["view"]["seats"][1:])
    path = f"/api/v1/hands/{hand['id']}"
    annotation = client.post(
        path + "/annotation", json={"bookmarked": True, "note": "Review flop sizing."}
    )
    assert annotation.status_code == 200 and annotation.json()["note"] == "Review flop sizing."
    assert len(client.get("/api/v1/hands?saved=true").json()["hands"]) == 1
    exported = client.get(path + "/export?format=json")
    assert exported.status_code == 200
    assert not {"deck", "decision_seed", "profile", "commands"}.intersection(
        json.loads(exported.text)
    )
    analysis = client.post(path + "/analysis", json={"decision": 0, "ranges": {}})
    assert analysis.status_code == 200 and analysis.json()["samples"] >= 32
    client.headers["Authorization"] = f"Bearer {bob}"
    for suffix in ("", "/export", "/export?format=json"):
        assert client.get(path + suffix).status_code == 404
    assert client.post(path + "/analysis", json={"decision": 0}).status_code == 404
    assert (
        client.post(path + "/annotation", json={"bookmarked": False, "note": ""}).status_code == 404
    )
    client.headers["Authorization"] = f"Bearer {alice}"
    with db.factory()() as conn, conn.begin():
        old_hand = conn.get(db.Hand, hand["id"])
        old_hand.decisions = []
        old_hand.summary = {
            k: v
            for k, v in old_hand.summary.items()
            if k not in {"session_id", "position", "big_blind", "players", "bookmarked", "note"}
        }
    assert client.get(path).status_code == 200
    assert client.post(path + "/analysis", json={"decision": 0}).status_code == 422


@db_test
def test_profile_validation_and_next_hand_name(client):
    assert client.post("/api/v1/me", json={"name": "   "}).status_code == 422
    assert client.post("/api/v1/me", json={"name": "bad\nname"}).status_code == 422
    response = client.post("/api/v1/me", json={"name": "Eshan", "preferences": {"pace": "manual"}})
    assert response.status_code == 200 and response.json()["preferences"]["pace"] == "manual"
    s = create(client)
    assert s["seats"][0]["name"] == "Eshan"


@db_test
def test_range_grid_uses_pokerkit_notation(client):
    client.post("/api/v1/guest", json={})
    response = client.post("/api/v1/ranges/expand", json={"range": "QQ+,AKs"})
    assert response.status_code == 200
    assert set(response.json()["hands"]) == {"QQ", "KK", "AA", "AKs"}
    assert client.post("/api/v1/ranges/expand", json={"range": "broken"}).status_code == 422
