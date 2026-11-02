"""Real, deterministic event batches for browser presentation tests; no database access."""

import json
from random import Random
from unittest.mock import patch
from uuid import uuid4

from deepstack import session
from deepstack.schemas import Command, TableConfig


def fixture(players=6, scenario="checkdown"):
    config = TableConfig(
        players=players,
        seat_stacks=[60000, 20000, 40000] if scenario == "side-pot" else None,
    )
    table = session.new_table("00000000-0000-4000-8000-000000000001", config, rng=Random(42))
    initial = session.snapshot(table).model_dump()
    batches, replays = [], []
    with patch(
        "deepstack.bots.choose",
        side_effect=lambda v, *_: {"kind": "call" if v.legal.call else "check"},
    ):
        for number in range(1, 3):
            session.start_hand(table, 42 + number)
            if scenario == "side-pot":
                # Exercise separate main/side-pot winners, then keep the hero funded.
                ranks = {0: "K" if number == 1 else "A", 1: "A" if number == 1 else "K", 2: "Q"}
                prefix = [ranks[seat] + suit for suit in "hc" for seat in table["hand"]["mapping"]]
                prefix += ["2d", "3s", "7d", "9h", "Td", "4s", "5d", "Js"]
                table["hand"]["deck"] = prefix + [
                    card for card in table["hand"]["deck"] if card not in prefix
                ]
            state = session.advance(table)
            after = 0
            for _ in range(30):
                public = session.snapshot(table, state).model_dump()
                events = [e for e in table["hand"]["events"] if e["id"] > after]
                batches.append({"snapshot": public, "events": events})
                after = table["event_id"]
                if public["complete"]:
                    break
                legal = public["legal"]
                action = {"kind": "call" if legal["call"] else "check"}
                if scenario == "fold" and legal["fold"]:
                    action = {"kind": "fold"}
                if scenario == "side-pot" and legal["max_raise_to"]:
                    action = {"kind": "raise_to", "amount": legal["max_raise_to"]}
                state, _ = session.command(
                    table,
                    Command(
                        command_id=uuid4(),
                        expected_version=table["version"],
                        kind="act",
                        action=action,
                    ),
                )
            else:
                raise AssertionError("Fixture hand did not complete")
            hand = table["hand"]
            replays.append(
                {
                    "hand": {
                        "id": hand["id"],
                        "session_id": table["id"],
                        "number": number,
                        "board": public["board"],
                        "hero_cards": hand["hero_cards"],
                        "profit": 0,
                        "pot": hand["final_pot"],
                        "created_at": table["created_at"],
                        "position": "BTN",
                        "big_blind": config.big_blind,
                        "players": players,
                        "bookmarked": False,
                        "note": "",
                    },
                    "events": hand["events"],
                    "decisions": hand.get("decisions", []),
                }
            )
    return {"initial": initial, "batches": batches, "replays": replays}


if __name__ == "__main__":
    import sys

    print(json.dumps(fixture(int(sys.argv[1]), sys.argv[2])))
