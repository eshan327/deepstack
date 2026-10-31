"""Only the browser-test harness imports this. There is deliberately no fixture API route."""

import copy
import sys
from uuid import uuid4

from sqlalchemy import select

from deepstack import db, engine, session
from deepstack.schemas import Command
from main import save_result

sid, scenario = sys.argv[1:]
if scenario not in ("side-pot", "nine-max"):
    raise ValueError("Unknown browser fixture")
with db.factory()() as conn, conn.begin():
    row = conn.scalar(select(db.GameSession).where(db.GameSession.id == sid).with_for_update())
    if not row or row.version != 0 or row.state["hand"] is not None:
        raise ValueError("Fixtures can only initialize the newly created test table")
    table = copy.deepcopy(row.state)
    session.start_hand(table, 73103)
    if scenario == "side-pot":
        assert len(table["seats"]) == 3
        cards = ["Kh", "Qh", "Ah", "Kc", "Qc", "Ac", "2d", "3s", "7d", "9h", "Td", "4s", "5d", "Js"]
        table["hand"]["deck"] = cards + [c for c in table["hand"]["deck"] if c not in cards]
    state = engine.restore(table)
    while engine.advance_forced(table, state):
        pass
    if scenario == "side-pot":
        # Fix the public betting situation, not bot personalities or willingness to call.
        for action in (
            {"kind": "raise_to", "amount": 20000},
            {"kind": "call"},
            {"kind": "raise_to", "amount": 40000},
        ):
            engine.act(table, state, action)
            while engine.advance_forced(table, state):
                pass
    if scenario == "nine-max":
        assert len(table["seats"]) == 9
        engine.act(table, state, {"kind": "raise_to", "amount": 60000})
        while state.status:
            if engine.advance_forced(table, state):
                continue
            engine.act(
                table, state, {"kind": "call" if state.checking_or_calling_amount else "check"}
            )
        session.settle(table, state)
    assert not state.status or table["hand"]["mapping"][state.actor_index] == 0
    table["version"] = 1
    row.state = table
    save_result(
        conn, row.guest_id, row, Command(command_id=uuid4(), expected_version=0, kind="next_hand")
    )
print(f"Initialized {scenario} test table.")
