import copy
import hashlib
import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pokerkit import parse_range
from sqlalchemy import and_, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from deepstack import auth, db, session
from deepstack.analysis import analyze
from deepstack.schemas import (
    AnalysisRequest,
    AnalysisResult,
    Annotation,
    Command,
    CommandResult,
    CreateSession,
    DecisionContext,
    GuestResult,
    HandList,
    HandSummary,
    LedgerList,
    Profile,
    ProfileUpdate,
    RangeExpansion,
    RangeRequest,
    Replay,
    ReviewHands,
    SessionList,
    SessionSummary,
)

app = FastAPI(title="Deepstack", version="1.0.0", docs_url=None, redoc_url=None)
COOKIE = "deepstack_guest"
log = logging.getLogger("deepstack")


@app.middleware("http")
async def protect(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
        if origin and urlparse(origin).netloc != host:
            return Response(
                status_code=403,
                content='{"detail":"Cross-origin request rejected."}',
                media_type="application/json",
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return Response(status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def connection():
    try:
        with db.factory()() as conn, conn.begin():
            yield conn
    except SQLAlchemyError:
        log.error("Database request failed; transaction rolled back.")
        raise HTTPException(
            503, "The table could not be saved. Your last saved state is safe. Retry shortly."
        ) from None


def owner(request: Request, conn: Session = Depends(connection, scope="function")) -> str:
    identity = auth.identity(request)
    if identity:
        subject = identity["sub"]
        name = str(identity.get("name") or "You").strip()[:32]
        name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127) or "You"
        conn.execute(
            insert(db.Account)
            .values(id=subject, name=name, preferences={}, table_defaults={})
            .on_conflict_do_nothing()
        )
        key = hashlib.sha256(f"account:{subject}".encode()).hexdigest()
        conn.execute(
            insert(db.Guest)
            .values(id=key, account_id=subject, name=name, preferences={}, table_defaults={})
            .on_conflict_do_nothing()
        )
        return key
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        raise HTTPException(401, "Establish a guest session first.")
    key = hashlib.sha256(token.encode()).hexdigest()
    row = conn.get(db.Guest, key)
    if not row or row.account_id:
        raise HTTPException(401, "This guest session is unavailable.")
    return key


def owner_ids(conn, guest):
    row = conn.get(db.Guest, guest)
    return (
        select(db.Guest.id).where(db.Guest.account_id == row.account_id)
        if row.account_id
        else [guest]
    )


def profile_row(conn, guest):
    row = conn.get(db.Guest, guest)
    return conn.get(db.Account, row.account_id) if row.account_id else row


def owned(conn, guest: str, sid: str, lock=False):
    query = select(db.GameSession).where(
        db.GameSession.id == sid, db.GameSession.guest_id.in_(owner_ids(conn, guest))
    )
    if lock:
        query = query.with_for_update()
    row = conn.scalar(query)
    if row is None:
        raise HTTPException(404, "Table not found.")
    return row


def fingerprint(payload) -> str:
    data = payload.model_dump(mode="json")
    if data.get("previous_session_id") is None:
        data.pop("previous_session_id", None)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def duplicate(conn, guest, cmd, sid):
    receipt = conn.get(db.Receipt, (guest, str(cmd.command_id)))
    if receipt:
        if receipt.session_id != sid or receipt.request_hash != fingerprint(cmd):
            raise HTTPException(409, "This command ID was already used for another request.")
        return receipt.response
    return None


def save_result(conn, guest, row, cmd, after=0):
    table = row.state
    hand = table.get("hand")
    if hand and hand["settled"] and not conn.get(db.Hand, hand["id"]):
        hero = hand["mapping"].index(0)
        summary = HandSummary(
            id=hand["id"],
            number=table["hand_number"],
            board=session.engine.view(table).board,
            hero_cards=hand["hero_cards"],
            profit=table["seats"][0]["stack"] - hand["stacks"][hero],
            pot=hand["final_pot"],
            created_at=db.now().isoformat(),
            session_id=row.id,
            position=hand["events"][0]["view"]["seats"][0]["position"],
            big_blind=table["config"]["big_blind"],
            players=table["config"]["players"],
        )
        conn.add(
            db.Hand(
                id=hand["id"],
                session_id=row.id,
                number=table["hand_number"],
                summary=summary.model_dump(),
                events=hand["events"],
                decisions=hand.get("decisions", []),
            )
        )
    for seat in table["seats"]:
        identity = seat.get("opponent_id") or seat["profile"]
        memory = conn.get(db.Memory, (guest, identity))
        if not memory:
            memory = db.Memory(guest_id=guest, profile=identity)
            conn.add(memory)
        memory.observed = copy.deepcopy(seat["observed"])
        memory.note = seat["note"]
    result = CommandResult(
        snapshot=session.snapshot(table),
        events=[e for e in hand["events"] if e["id"] > after] if hand else [],
    )
    row.version, row.status = table["version"], table["status"]
    conn.add(
        db.Receipt(
            guest_id=guest,
            command_id=str(cmd.command_id),
            session_id=row.id,
            request_hash=fingerprint(cmd),
            response=result.model_dump(),
        )
    )
    conn.flush()
    return result


@app.get("/api/v1/health")
def health(conn: Session = Depends(connection, scope="function")):
    conn.execute(text("SELECT 1"))
    return {"ready": True, "engine": session.engine.ENGINE_VERSION}


@app.post("/api/v1/guest", response_model=GuestResult)
def guest(
    request: Request, response: Response, conn: Session = Depends(connection, scope="function")
):
    token = request.cookies.get(COOKIE)
    key = hashlib.sha256(token.encode()).hexdigest() if token and len(token) <= 128 else None
    prior = conn.get(db.Guest, key) if key else None
    if not prior or prior.account_id:
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode()).hexdigest()
        conn.add(db.Guest(id=key))
    secure = (
        bool(os.environ.get("VERCEL"))
        or request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
        path="/",
    )
    return GuestResult(ready=True)


@app.get("/api/v1/sessions", response_model=SessionList)
def sessions(guest: str = Depends(owner), conn: Session = Depends(connection, scope="function")):
    rows = conn.scalars(
        select(db.GameSession)
        .where(db.GameSession.guest_id.in_(owner_ids(conn, guest)))
        .order_by(db.GameSession.created_at.desc())
        .limit(100)
    ).all()
    return SessionList(
        sessions=[
            SessionSummary(
                id=r.id,
                status=r.status,
                hands=r.state["hands_played"],
                profit=r.state["profit"],
                created_at=r.created_at.isoformat(),
                config=r.state["config"],
            )
            for r in rows
        ]
    )


@app.post("/api/v1/sessions", response_model=CommandResult)
def create(
    cmd: CreateSession,
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    if cmd.previous_session_id:
        previous = owned(conn, guest, str(cmd.previous_session_id))
        if previous.status != "ended":
            raise HTTPException(409, "Finish and cash out the selected table first.")
        guest = previous.guest_id
    # Serialize creates and all session mutations per guest; row locks work through PgBouncer.
    conn.scalar(select(db.Guest).where(db.Guest.id == guest).with_for_update())
    receipt = conn.get(db.Receipt, (guest, str(cmd.command_id)))
    if receipt:
        if receipt.request_hash != fingerprint(cmd):
            raise HTTPException(409, "This command ID has already been used.")
        return receipt.response
    if conn.scalar(
        select(db.GameSession.id).where(
            db.GameSession.guest_id == guest, db.GameSession.status == "active"
        )
    ):
        raise HTTPException(409, "Resume or end your current table before starting another.")
    memories = {
        m.profile: {"observed": m.observed, "note": m.note}
        for m in conn.scalars(select(db.Memory).where(db.Memory.guest_id == guest))
    }
    sid = str(uuid4())
    table = session.new_table(sid, cmd.config, memories, hero_name=profile_row(conn, guest).name)
    row = db.GameSession(id=sid, guest_id=guest, state=table)
    conn.add(row)
    conn.flush()
    for seat in table["seats"]:
        conn.add(db.Ledger(session_id=sid, seat=seat["seat"], kind="buy_in", amount=seat["stack"]))
    return save_result(conn, guest, row, cmd)


@app.get("/api/v1/sessions/{sid}", response_model=CommandResult)
def read(
    sid: str,
    after_event_id: int = Query(default=0, ge=0),
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    row = owned(conn, guest, sid)
    hand = row.state.get("hand")
    return CommandResult(
        snapshot=session.snapshot(row.state),
        events=[e for e in hand["events"] if e["id"] > after_event_id] if hand else [],
    )


@app.post("/api/v1/sessions/{sid}/commands", response_model=CommandResult)
def mutate(
    sid: str,
    cmd: Command,
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    conn.scalar(select(db.Guest).where(db.Guest.id == guest).with_for_update())
    row = owned(conn, guest, sid, lock=True)
    guest = row.guest_id
    result = duplicate(conn, guest, cmd, sid)
    if result is not None:
        return result
    if row.version != cmd.expected_version:
        raise HTTPException(
            409, "The table changed in another tab. Reloading the current state is safe."
        )
    table = copy.deepcopy(row.state)
    after = table["event_id"]
    try:
        if cmd.kind == "next_hand":
            table["seats"][0]["name"] = profile_row(conn, guest).name
        _, ledger = session.command(table, cmd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    row.state = table
    for seat, kind, amount in ledger:
        conn.add(db.Ledger(session_id=sid, seat=seat, kind=kind, amount=amount))
    return save_result(conn, guest, row, cmd, after)


@app.get("/api/v1/sessions/{sid}/hands", response_model=HandList)
def hands(
    sid: str,
    before: int | None = Query(default=None, ge=1),
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    owned(conn, guest, sid)
    query = select(db.Hand).where(db.Hand.session_id == sid)
    if before is not None:
        query = query.where(db.Hand.number < before)
    rows = conn.scalars(query.order_by(db.Hand.number.desc()).limit(21)).all()
    return HandList(
        hands=[hand_summary(conn, r) for r in rows[:20]],
        next_before=rows[19].number if len(rows) > 20 else None,
    )


@app.get("/api/v1/sessions/{sid}/hands/{hid}", response_model=Replay)
def replay(
    sid: str,
    hid: str,
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    owned(conn, guest, sid)
    row = conn.scalar(select(db.Hand).where(db.Hand.id == hid, db.Hand.session_id == sid))
    if not row:
        raise HTTPException(404, "Hand not found.")
    return Replay(hand=hand_summary(conn, row), events=row.events, decisions=row.decisions)


@app.get("/api/v1/sessions/{sid}/ledger", response_model=LedgerList)
def ledger(
    sid: str,
    before: int | None = Query(default=None, ge=1),
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    owned(conn, guest, sid)
    query = select(db.Ledger).where(db.Ledger.session_id == sid)
    if before is not None:
        query = query.where(db.Ledger.id < before)
    rows = conn.scalars(query.order_by(db.Ledger.id.desc()).limit(51)).all()
    return LedgerList(
        entries=[
            {
                "id": r.id,
                "seat": r.seat,
                "kind": r.kind,
                "amount": r.amount,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows[:50]
        ],
        next_before=rows[49].id if len(rows) > 50 else None,
    )


def hand_summary(conn, row):
    data = dict(row.summary)
    data.update(session_id=row.session_id, bookmarked=row.bookmarked, note=row.note)
    if "big_blind" not in data:
        table = conn.get(db.GameSession, row.session_id).state
        first = row.events[0]["view"] if row.events else None
        data.update(
            big_blind=table["config"]["big_blind"],
            players=table["config"]["players"],
            position=first["seats"][0]["position"] if first else "",
        )
    return HandSummary.model_validate(data)


@app.get("/api/v1/me", response_model=Profile)
def me(guest: str = Depends(owner), conn: Session = Depends(connection, scope="function")):
    row = profile_row(conn, guest)
    return Profile(
        name=row.name,
        preferences=row.preferences,
        table_defaults=row.table_defaults,
        authenticated=isinstance(row, db.Account),
        auth_available=bool(
            os.environ.get("NEON_AUTH_BASE_URL") and os.environ.get("NEON_AUTH_COOKIE_SECRET")
        ),
    )


@app.post("/api/v1/me", response_model=Profile)
def update_me(
    data: ProfileUpdate,
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    row = profile_row(conn, guest)
    row.name = data.name
    row.preferences = data.preferences.model_dump()
    row.table_defaults = data.table_defaults.model_dump()
    return me(guest, conn)


@app.post("/api/v1/me/claim", response_model=Profile)
def claim(
    request: Request,
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    target = conn.get(db.Guest, guest)
    if not target.account_id:
        raise HTTPException(401, "Sign in before saving guest history to your account.")
    conn.scalar(select(db.Account).where(db.Account.id == target.account_id).with_for_update())
    token = request.cookies.get(COOKIE)
    if token and len(token) <= 128:
        key = hashlib.sha256(token.encode()).hexdigest()
        source = conn.scalar(select(db.Guest).where(db.Guest.id == key).with_for_update())
        if source and source.account_id not in (None, target.account_id):
            raise HTTPException(409, "This browser history already belongs to another account.")
        if source and source.account_id is None:
            account = conn.get(db.Account, target.account_id)
            if source.name != "You" and account.name == "You":
                account.name = source.name
            if not account.preferences:
                account.preferences = source.preferences
                account.table_defaults = source.table_defaults
            source.account_id = target.account_id
    return me(guest, conn)


@app.post("/api/v1/guest/reset", response_model=GuestResult)
def reset_guest(
    response: Response, request: Request, conn: Session = Depends(connection, scope="function")
):
    response.delete_cookie(COOKIE)
    token = secrets.token_urlsafe(32)
    conn.add(db.Guest(id=hashlib.sha256(token.encode()).hexdigest()))
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=31536000,
        secure=bool(os.environ.get("VERCEL"))
        or request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
    )
    return GuestResult(ready=True)


@app.get("/api/v1/hands", response_model=ReviewHands)
def review_hands(
    session_id: str | None = None,
    before: str | None = None,
    saved: bool = False,
    days: int | None = Query(default=None, ge=1, le=36500),
    big_blind: int | None = Query(default=None, ge=1),
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    query = (
        select(db.Hand)
        .join(db.GameSession)
        .where(db.GameSession.guest_id.in_(owner_ids(conn, guest)))
    )
    if session_id:
        owned(conn, guest, session_id)
        query = query.where(db.Hand.session_id == session_id)
    if saved:
        query = query.where(db.Hand.bookmarked.is_(True))
    if days:
        query = query.where(db.Hand.created_at >= datetime.now(UTC) - timedelta(days=days))
    if big_blind:
        query = query.where(db.GameSession.state["config"]["big_blind"].as_integer() == big_blind)
    if before:
        try:
            stamp, hid = before.split("|", 1)
            when = datetime.fromisoformat(stamp)
            if when.tzinfo is None:
                raise ValueError()
            query = query.where(
                or_(
                    db.Hand.created_at < when,
                    and_(db.Hand.created_at == when, db.Hand.id < str(UUID(hid))),
                )
            )
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid history cursor.") from None
    rows = conn.scalars(
        query.order_by(db.Hand.created_at.desc(), db.Hand.id.desc()).limit(26)
    ).all()
    return ReviewHands(
        hands=[hand_summary(conn, r) for r in rows[:25]],
        next_cursor=f"{rows[24].created_at.isoformat()}|{rows[24].id}" if len(rows) > 25 else None,
    )


@app.post("/api/v1/ranges/expand", response_model=RangeExpansion)
def expand_range(data: RangeRequest, guest: str = Depends(owner)):
    from deepstack.bots import ALL_COMBOS

    try:
        combos = ALL_COMBOS if data.range.lower() == "random" else parse_range(data.range)
        labels = set()
        order = "AKQJT98765432"
        for combo in combos:
            if len(combo) != 2:
                raise ValueError()
            a, b = sorted((repr(c) for c in combo), key=lambda c: order.index(c[0]))
            labels.add(a[0] + b[0] + ("" if a[0] == b[0] else "s" if a[1] == b[1] else "o"))
        if not labels:
            raise ValueError()
        return RangeExpansion(hands=sorted(labels))
    except (ValueError, KeyError, IndexError, AssertionError):
        raise HTTPException(
            422, "Use valid Hold’em range notation, such as 77+, AJs+, KQs."
        ) from None


def owned_hand(conn, guest, hid):
    row = conn.scalar(
        select(db.Hand)
        .join(db.GameSession)
        .where(db.Hand.id == hid, db.GameSession.guest_id.in_(owner_ids(conn, guest)))
    )
    if not row:
        raise HTTPException(404, "Hand not found.")
    return row


@app.get("/api/v1/hands/{hid}", response_model=Replay)
def review_hand(
    hid: str, guest: str = Depends(owner), conn: Session = Depends(connection, scope="function")
):
    row = owned_hand(conn, guest, hid)
    return Replay(hand=hand_summary(conn, row), events=row.events, decisions=row.decisions)


@app.post("/api/v1/hands/{hid}/annotation", response_model=HandSummary)
def annotate(
    hid: str,
    data: Annotation,
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    row = owned_hand(conn, guest, hid)
    row.bookmarked, row.note = data.bookmarked, data.note
    return hand_summary(conn, row)


@app.post("/api/v1/hands/{hid}/analysis", response_model=AnalysisResult)
def decision_analysis(
    hid: str,
    data: AnalysisRequest,
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    row = owned_hand(conn, guest, hid)
    if data.decision >= len(row.decisions):
        raise HTTPException(422, "No saved decision context is available for this hand.")
    context = DecisionContext.model_validate(row.decisions[data.decision])
    try:
        return analyze(context, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@app.get("/api/v1/hands/{hid}/export")
def export_hand(
    hid: str,
    format: str = Query(default="text", pattern="^(text|json)$"),
    guest: str = Depends(owner),
    conn: Session = Depends(connection, scope="function"),
):
    row = owned_hand(conn, guest, hid)
    safe = Replay(hand=hand_summary(conn, row), events=row.events, decisions=row.decisions)
    body = (
        safe.model_dump_json(indent=2)
        if format == "json"
        else "\n".join(
            [
                f"Deepstack · Hand #{row.number} · Simulated money",
                f"Hero: {' '.join(safe.hand.hero_cards)} · Result ${safe.hand.profit / 100:.2f}",
                *(event.text for event in safe.events),
            ]
        )
    )
    return Response(
        body,
        media_type="application/json" if format == "json" else "text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="deepstack-{row.id}.{format if format == "json" else "txt"}"'
        },
    )
