import copy
import json
from dataclasses import replace
from random import Random
from uuid import uuid4

import pytest

from deepstack import bots, engine, session
from deepstack.schemas import Action, Command, TableConfig


def table(players=3, stacks=None, sb=10, bb=20, deck=None):
    t = session.new_table(
        "test",
        TableConfig(
            players=players, small_blind=sb, big_blind=bb, starting_stack=1000, seat_stacks=stacks
        ),
    )
    session.start_hand(t, 42)
    if deck:
        prefix = deck.split()
        t["hand"]["deck"] = prefix + [c for c in t["hand"]["deck"] if c not in prefix]
    s = engine.restore(t)
    forced(t, s)
    return t, s


def forced(t, s):
    for _ in range(100):
        if not s.status or not engine.advance_forced(t, s):
            return
    raise AssertionError("Forced operations did not settle")


def act(t, s, kind, amount=None):
    engine.act(t, s, {"kind": kind, "amount": amount})
    forced(t, s)


def finish(t, s):
    for _ in range(50):
        forced(t, s)
        if not s.status:
            session.settle(t, s)
            return
        act(t, s, "call" if s.checking_or_calling_amount else "check")
    raise AssertionError("Hand stuck")


def test_heads_up_button_posts_small_blind_and_acts_first():
    t, s = table(2)
    assert t["hand"]["mapping"] == [1, 0]
    assert s.actor_index == 1
    assert s.bets == [20, 10]
    act(t, s, "call")
    act(t, s, "check")
    assert s.street_index == 1
    assert t["hand"]["mapping"][s.actor_index] == 1


def test_position_labels_follow_button_for_two_to_nine_players():
    expected = {
        2: ["BB", "BTN"],
        3: ["SB", "BB", "BTN"],
        4: ["SB", "BB", "CO", "BTN"],
        5: ["SB", "BB", "HJ", "CO", "BTN"],
        6: ["SB", "BB", "UTG", "HJ", "CO", "BTN"],
        7: ["SB", "BB", "UTG", "LJ", "HJ", "CO", "BTN"],
        8: ["SB", "BB", "UTG", "UTG+1", "LJ", "HJ", "CO", "BTN"],
        9: ["SB", "BB", "UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN"],
    }
    for players, labels in expected.items():
        t, s = table(players)
        public = engine.view(t, s)
        assert [public.seats[i].position for i in t["hand"]["mapping"]] == labels
        assert public.seats[0].position == "BTN"
        finish(t, s)
        session.start_hand(t, 43)
        s = engine.restore(t)
        forced(t, s)
        public = engine.view(t, s)
        assert [public.seats[i].position for i in t["hand"]["mapping"]] == labels
        assert public.seats[1].position == "BTN"


def test_raise_to_limits_and_no_free_fold():
    t, s = table()
    legal = engine.legal_actions(s, 20)
    assert legal.call == 20 and legal.min_raise_to == 40
    with pytest.raises(ValueError):
        engine.act(t, s, {"kind": "raise_to", "amount": 30})
    act(t, s, "raise_to", 60)
    assert engine.legal_actions(s, 20).min_raise_to == 100


def test_short_all_in_does_not_reopen_action():
    t, s = table(stacks=[1000, 1000, 350], sb=50, bb=100)
    act(t, s, "raise_to", 300)
    act(t, s, "call")
    act(t, s, "raise_to", 350)
    assert t["hand"]["mapping"][s.actor_index] == 0
    assert engine.legal_actions(s, 100).min_raise_to is None
    assert engine.legal_actions(s, 100).call == 50
    finish(t, s)
    assert sum(s.stacks) == 2350


def test_uncalled_raise_returned_when_everyone_folds():
    t, s = table()
    act(t, s, "raise_to", 1000)
    act(t, s, "fold")
    act(t, s, "fold")
    assert s.status is False
    assert s.stacks == [990, 980, 1030]


def test_multiway_all_in_side_pots_and_no_duplicate_cards():
    t, s = table(stacks=[600, 200, 400], deck="Kh Qh Ah Kc Qc Ac 2d 3s 7d 9h Td 4s 5d Js")
    act(t, s, "raise_to", 600)
    act(t, s, "call")
    act(t, s, "call")
    assert s.status is False
    assert s.stacks == [0, 0, 1200]
    assert t["hand"]["winnings"] == {"0": 1000}
    shown = list(t["hand"]["shown"].values())
    cards = [c for hand in shown for c in hand] + engine.view(t, s).board
    assert len(cards) == len(set(cards))


def test_tie_and_odd_chip_go_to_first_eligible_after_button():
    t, s = table(
        stacks=[100, 100, 100], sb=1, bb=2, deck="Qc Ah As Jc Kd Kh 2s 3h 4d 7c 8c 9d Tc Js"
    )
    act(t, s, "call")
    act(t, s, "fold")
    act(t, s, "check")
    finish(t, s)
    assert s.stacks == [99, 101, 100]


def test_restore_every_decision_matches_engine_and_safe_view():
    t, s = table(6)
    for _ in range(80):
        restored = engine.restore(copy.deepcopy(t))
        assert restored.stacks == s.stacks
        assert restored.bets == s.bets
        assert restored.actor_index == s.actor_index
        assert engine.view(t, restored) == engine.view(t, s)
        if not s.status:
            break
        act(t, s, "call" if s.checking_or_calling_amount else "check")
    assert not s.status


def test_no_private_cards_or_strategy_in_snapshots_and_events():
    t, s = table(6)
    public = json.dumps(session.snapshot(t, s).model_dump())
    events = json.dumps(t["hand"]["events"])
    for i, seat in enumerate(t["hand"]["mapping"]):
        if seat:
            for card in s.hole_cards[i]:
                assert repr(card) not in public
                assert repr(card) not in events
    assert not any(k in public for k in ("decision_seed", '"deck"', '"profile"'))


def test_seeded_bot_ignores_unseen_human_cards_and_deck():
    t, s = table(6)
    act(t, s, "call")
    v = session.bot_view(t, s)
    p = bots.PROFILES[0]
    decision = bots.choose(v, p, Random(8))
    hero = t["hand"]["mapping"].index(0)
    s.hole_cards[hero].reverse()
    s.deck_cards.reverse()
    t["hand"]["hero_cards"] = ["As", "Ad"]
    assert session.bot_view(t, s) == v
    assert bots.choose(session.bot_view(t, s), p, Random(8)) == decision


def test_sit_out_button_rotation_rebuy_and_topup():
    t, s = table(4)
    finish(t, s)
    expected_profit = t["profit"]
    t["seats"][1]["sitting_out"] = True
    t["seats"][2]["stack"] = 0
    assert session.start_hand(t, 44) == [(2, 1000)]
    assert t["button"] == 2
    assert 1 not in t["hand"]["mapping"]
    finish(t, engine.restore(t))
    profit = t["profit"]
    cmd = Command(command_id=uuid4(), expected_version=0, kind="top_up", seat=0, amount=200)
    session.command(t, cmd)
    assert t["profit"] == profit
    assert t["buy_ins"] == 1200
    assert session.snapshot(t).complete
    assert session.snapshot(t).seats[0].stack == t["seats"][0]["stack"]
    assert isinstance(expected_profit, int)


def test_chip_values_are_strict_integers():
    with pytest.raises(ValueError):
        Action(kind="raise_to", amount=2.5)
    with pytest.raises(ValueError):
        TableConfig(small_blind=True)
    with pytest.raises(ValueError):
        TableConfig(players=2, seat_stacks=[100])


def test_commands_reject_extra_or_missing_fields():
    with pytest.raises(ValueError):
        Command(command_id=uuid4(), expected_version=0, kind="next_hand", amount=100)
    with pytest.raises(ValueError):
        Command(command_id=uuid4(), expected_version=0, kind="top_up", seat=0)


def test_pot_presets_include_call_and_outstanding_wagers():
    t, s = table()
    act(t, s, "call")
    act(t, s, "call")
    act(t, s, "check")
    presets = {p.label: p.amount for p in engine.legal_actions(s, 20).presets}
    assert presets["½ pot"] == 30 and presets["Pot"] == 60
    act(t, s, "raise_to", 40)
    presets = {p.label: p.amount for p in engine.legal_actions(s, 20).presets}
    assert presets["½ pot"] == 110 and presets["Pot"] == 180


def test_equity_sampling_honors_weights_and_ties(monkeypatch):
    t, s = table()
    v = replace(
        session.bot_view(t, s),
        cards=("Ac", "Ad"),
        board=("2c", "3d", "7h", "9s", "Jc"),
        opponents=((1, 0, 0),),
    )
    monkeypatch.setattr(
        bots, "opponent_combos", lambda *args: ([("Kc", "Kd"), ("Jd", "Jh")], [99, 1])
    )
    assert 0.96 < bots.equity(v, Random(8), 500) <= 1.0
    monkeypatch.undo()
    v = replace(v, cards=("2h", "3d"), board=("As", "Ks", "Qs", "Js", "Ts"))
    assert bots.equity(v, Random(8), 32) == 0.5


def test_seeded_simulation_decisions_repeat():
    logs = []
    for _ in range(2):
        t = session.new_table("test", TableConfig(players=6))
        session.start_hand(t, 73103)
        session.advance(t, stop_at_hero=False, samples=12)
        logs.append(t["hand"]["public_actions"])
    assert logs[0] == logs[1]


def test_opponent_field_presets_apply_at_every_table_size():
    for count in range(2, 10):
        soft = session.new_table("soft", TableConfig(players=count, field="soft"))
        tough = session.new_table("tough", TableConfig(players=count, field="tough"))
        assert soft["seats"][1]["profile"] == "eli"
        assert tough["seats"][1]["profile"] == "theo"
