import copy
import json
from collections import Counter
from dataclasses import replace
from random import Random

import pytest
from pokerkit import Card

from deepstack import bots, engine, opponents, session
from deepstack.schemas import LegalActions, TableConfig
from tests.test_engine import act, finish, table


def model(attention=1.0):
    result = opponents.sample("balanced", Random(19))
    result["traits"]["attentiveness"] = attention
    return result


def train(m, values, hands=80):
    rng = Random(52)
    for _ in range(hands):
        opponents.observe(m, {"hero": values}, rng)
    return m


def test_population_has_continuous_diversity_and_names_are_cosmetic():
    rng = Random(41)
    population = [opponents.sample("balanced", rng)["traits"] for _ in range(500)]
    assert len({p["looseness"] for p in population}) > 450
    assert all(
        any(
            p["looseness"] < 1 if tight else p["looseness"] > 1.5
            for p in population
            if (p["aggression"] > 0.65) == aggressive
        )
        for tight in (True, False)
        for aggressive in (True, False)
    )
    assert any(p["sizing_tell"] < -0.2 for p in population)
    assert any(p["sizing_tell"] > 0.2 for p in population)
    tables = [session.new_table("same", TableConfig(players=2), rng=Random(i)) for i in range(30)]
    for t in tables:
        t["seats"][1]["name"] = "Iris"
    assert len({t["seats"][1]["bot"]["traits"]["looseness"] for t in tables}) == 30


def test_public_evidence_tracks_real_opportunities_and_only_shown_cards():
    actions = [
        [0, 0, "raise_to", 60],
        [1, 0, "call", 60],
        [2, 0, "fold", 0],
        [1, 1, "check", 0],
        [0, 1, "raise_to", 80],
        [1, 1, "fold", 0],
    ]
    observed = opponents.evidence(actions, [0, 1, 2], {}, ["Ac", "7h", "2s"])
    assert observed[0] == {"vpip": 1, "pfr": 1}
    assert observed[1] == {"vpip": 1, "pfr": 0, "three_bet": 0, "fold_cbet": 1}
    assert observed[2] == {"vpip": 0, "pfr": 0, "three_bet": 0}
    # A donk bet, or a fold to a raise over a cbet, is not a fold-to-cbet opportunity.
    donk = actions[:3] + [[1, 1, "raise_to", 80], [0, 1, "fold", 0]]
    assert all("fold_cbet" not in v for v in opponents.evidence(donk, [0, 1, 2], {}, []).values())
    raised_cbet = actions[:3] + [[0, 1, "raise_to", 80], [1, 1, "raise_to", 240], [0, 1, "fold", 0]]
    assert "fold_cbet" not in opponents.evidence(raised_cbet, [0, 1, 2], {}, [])[0]
    board = ["Ac", "7h", "2s", "9d", "Jh"]
    river = [[0, 3, "raise_to", 200]]
    assert "bluff" not in opponents.evidence(river, [0, 1], {}, board)[0]
    assert opponents.evidence(river, [0, 1], {"0": ["Kd", "Qc"]}, board)[0]["bluff"] == 1
    assert opponents.evidence(river, [0, 1], {"0": ["Ah", "Ad"]}, board)[0]["value"] == 1
    # Future public runout cards cannot turn a flop bluff into a flop value bet.
    flop = [[0, 1, "raise_to", 80]]
    assert opponents.evidence(flop, [0, 1], {"0": ["Kd", "Qc"]}, board)[0]["bluff"] == 1


def test_reads_learn_slowly_decay_and_keep_imperfect_first_impressions():
    attentive, distracted = model(1), model(0)
    observations = {"vpip": 1, "pfr": 1, "three_bet": 1, "fold_cbet": 0, "bluff": 1, "value": 0}
    opponents.observe(attentive, {"hero": observations}, Random(1))
    assert 0.3 < opponents.read(attentive, "hero", "vpip") < 0.4
    train(attentive, observations)
    train(distracted, observations)
    assert opponents.read(attentive, "hero", "vpip") > 0.7
    assert opponents.read(distracted, "hero", "vpip") < 0.4
    assert opponents.read(attentive, "hero", "bluff") > 0.65
    before = opponents.read(attentive, "hero", "vpip")
    for _ in range(150):
        opponents.observe(attentive, {}, Random(0))
    assert 0.3 < opponents.read(attentive, "hero", "vpip") < before - 0.2
    first_loose = train(model(), {"vpip": 1}, 20)
    first_tight = train(model(), {"vpip": 0}, 20)
    train(first_loose, {"vpip": 0}, 20)
    train(first_tight, {"vpip": 1}, 20)
    assert first_loose["reads"]["hero"]["vpip"]["first"] == 1
    assert first_tight["reads"]["hero"]["vpip"]["first"] == 0
    assert 0.3 < opponents.read(first_loose, "hero", "vpip") < 0.7
    assert 0.3 < opponents.read(first_tight, "hero", "vpip") < 0.7


def test_tilt_confidence_fatigue_lock_and_stack_effects():
    m = model()
    m["traits"]["tilt_sensitivity"] = 1
    base = opponents.effective(m, 100)
    m["state"]["own_equity"] = 0.9
    opponents.finish(m, -1000, 2000, 20, True, False, Random(1))
    tilted = opponents.effective(m, 100)
    assert m["state"]["tilt"] > 0.8
    assert tilted.looseness > base.looseness
    assert tilted.river_bluff > base.river_bluff
    assert m["state"]["own_equity"] is None
    fatigue = m["state"]["fatigue"]
    tilt = m["state"]["tilt"]
    opponents.finish(m, 0, 2000, 20, True, False, Random(2))
    assert m["state"]["tilt"] < tilt
    assert m["state"]["fatigue"] > fatigue
    # Seeded win occasionally locks up this tilt-prone identity.
    opponents.finish(m, 1500, 2000, 20, True, True, Random(1))
    assert m["state"]["confidence"] > 0
    assert m["state"]["lock"] > 0
    locked = opponents.effective(m, 100)
    m["state"]["lock"] = 0
    assert locked.looseness < opponents.effective(m, 100).looseness
    assert opponents.effective(m, 20).looseness < opponents.effective(m, 250).looseness
    old = m["state"]["fatigue"]
    opponents.finish(m, 0, 2000, 20, False, False, Random(1))
    assert m["state"]["fatigue"] < old
    modest_loss, bad_beat = model(), model()
    bad_beat["state"]["own_equity"] = 0.95
    for x in (modest_loss, bad_beat):
        opponents.finish(x, -100, 2000, 20, True, True, Random(1))
    assert bad_beat["state"]["tilt"] > modest_loss["state"]["tilt"]


def test_mixing_adaptation_and_generated_sizing_tells(monkeypatch):
    t, s = table(6)
    v = replace(session.bot_view(t, s), cards=("9h", "8h"), position="UTG")
    m = model()
    m["traits"].update(looseness=1.3, pfr=0.8)
    kinds = Counter(bots.choose(v, copy.deepcopy(m), Random(i))["kind"] for i in range(1000))
    assert kinds["fold"] > 100 and kinds["raise_to"] > 100 and kinds["call"] > 20
    nit = replace(v, opponents=(bots.Opponent(1, vpip=0.1, pfr=0.05),), fold_estimate=0.7)
    maniac = replace(v, opponents=(bots.Opponent(1, vpip=0.8, pfr=0.7),), fold_estimate=0.2)

    def raises(view):
        return sum(
            bots.choose(view, copy.deepcopy(m), Random(i))["kind"] == "raise_to"
            for i in range(1000)
        )

    assert raises(nit) > raises(maniac) + 150
    p = opponents.effective(m, 100)
    positive = replace(p, sizing_tell=0.4)
    negative = replace(p, sizing_tell=-0.4)
    assert bots.sizing(positive, Random(1), 1) > bots.sizing(positive, Random(1), 0)
    assert bots.sizing(negative, Random(1), 1) < bots.sizing(negative, Random(1), 0)
    # Same noisy equity, but a remembered bluffer gets more calls than a value bettor.
    monkeypatch.setattr(bots, "equity", lambda *args: 0.4)
    river = replace(
        v,
        board=("2c", "7d", "Jh", "Qs", "3c"),
        pot=300,
        legal=LegalActions(fold=True, call=200),
        actions=((1, 3, "raise_to", 200),),
    )
    bluff = replace(river, opponents=(bots.Opponent(1, bluff=0.8, value=0.2),))
    value = replace(river, opponents=(bots.Opponent(1, bluff=0.02, value=0.95),))

    def calls(view):
        return sum(
            bots.choose(view, copy.deepcopy(m), Random(i))["kind"] == "call" for i in range(1000)
        )

    assert calls(bluff) > calls(value) + 200


def test_reads_change_range_weights_and_shown_cards_are_used(monkeypatch):
    t, s = table(2)
    v = replace(
        session.bot_view(t, s),
        cards=("Ac", "Ad"),
        board=("2c", "3d", "7h", "9s", "Jc"),
        opponents=(bots.Opponent(1),),
        actions=((1, 3, "raise_to", 100),),
    )
    monkeypatch.setattr(
        bots, "opponent_combos", lambda *args: ([("Kc", "Kd"), ("8d", "6h")], [1, 1], [False, True])
    )
    honest = replace(v, opponents=(bots.Opponent(1, bluff=0.02, value=0.95),))
    bluff = replace(v, opponents=(bots.Opponent(1, bluff=0.8, value=0.2),))

    class RecordingRandom(Random):
        def choices(self, population, weights, k):
            self.weights = weights
            return super().choices(population, weights=weights, k=k)

    honest_rng, bluff_rng = RecordingRandom(1), RecordingRandom(1)
    bots.equity(honest, honest_rng, 1)
    bots.equity(bluff, bluff_rng, 1)
    assert (
        honest_rng.weights[1] / honest_rng.weights[0] < bluff_rng.weights[1] / bluff_rng.weights[0]
    )
    monkeypatch.undo()
    shown = replace(v, opponents=(bots.Opponent(1, cards=("Jd", "Jh")),))
    assert bots.equity(shown, Random(1), 10) == 0


def test_restore_never_decides_or_changes_models_and_settlement_is_once(monkeypatch):
    t = session.new_table("durable", TableConfig(players=6), rng=Random(1))
    for seat in t["seats"][1:]:
        seat["bot"]["traits"]["attentiveness"] = 1
    session.start_hand(t, 734)
    session.advance(t, stop_at_hero=False, samples=8)
    for seat in t["seats"][1:]:
        assert "hero" in seat["bot"]["reads"]
        assert seat["opponent_id"] not in seat["bot"]["reads"]
        assert seat["bot"]["state"]["hands"] == 1
        assert seat["bot"]["state"]["own_equity"] is None
    saved = json.loads(json.dumps(t))

    def unexpected(*args, **kwargs):
        pytest.fail("Replay attempted a bot decision or population sample")

    monkeypatch.setattr(bots, "choose", unexpected)
    monkeypatch.setattr(opponents, "sample", unexpected)
    restored = engine.restore(saved)
    assert session.snapshot(saved, restored) == session.snapshot(t)
    session.settle(saved, restored)
    assert saved == t
    traits = [s["bot"]["traits"] for s in saved["seats"][1:]]
    if not saved["seats"][0]["stack"]:
        saved["seats"][0]["stack"] = 60000
    session.start_hand(saved, 735)
    assert [s["bot"]["traits"] for s in saved["seats"][1:]] == traits


def test_legacy_session_upgrades_only_on_write_and_keeps_recorded_commands(monkeypatch):
    t, s = table(3)
    for seat in t["seats"][1:]:
        seat.pop("bot")
        seat["profile"] = "mara"
    recorded = copy.deepcopy(t["hand"]["commands"])
    before = copy.deepcopy(t)
    engine.restore(t)
    session.snapshot(t)
    assert t == before
    a, b = copy.deepcopy(t), copy.deepcopy(t)
    a["seats"][1]["profile"], a["seats"][1]["name"] = "eli", "Eli"
    assert session.model_for(a, a["seats"][1]) == session.model_for(b, b["seats"][1])
    assert t["hand"]["commands"] == recorded
    finish(t, s)
    assert all("bot" in seat for seat in t["seats"][1:])


def test_unseen_cards_private_statistics_and_other_models_cannot_change_a_decision():
    t, s = table(3)
    act(t, s, "call")
    act(t, s, "call")
    act(t, s, "check")
    v = session.bot_view(t, s)
    actor = t["hand"]["mapping"][s.actor_index]
    original = copy.deepcopy(t["seats"][actor]["bot"])
    decision = bots.choose(v, copy.deepcopy(original), Random(2), 12)
    for i, seat in enumerate(t["hand"]["mapping"]):
        if seat != actor:
            s.hole_cards[i] = list(Card.parse("AsAd"))
            t["seats"][seat]["observed"]["vpip"] = 10000
            if "bot" in t["seats"][seat]:
                t["seats"][seat]["bot"]["traits"]["looseness"] = 99
    s.deck_cards.reverse()
    t["hand"]["hero_cards"] = ["As", "Ad"]
    assert session.bot_view(t, s) == v
    assert bots.choose(session.bot_view(t, s), copy.deepcopy(original), Random(2), 12) == decision


def test_equity_attempts_and_advance_samples_stay_bounded(monkeypatch):
    t, s = table(6)
    v = replace(session.bot_view(t, s), opponents=(bots.Opponent(1),))
    monkeypatch.setattr(bots, "opponent_combos", lambda *args: ([v.cards], [1], [False]))

    class CollidingRandom(Random):
        attempts = 0

        def choices(self, population, weights, k):
            self.attempts += 1
            return [population[0]]

    rng = CollidingRandom(1)
    assert bots.equity(v, rng, 3) == 0.25
    assert rng.attempts == 3 * 16
    seen = []

    def passive_only(view, model, rng, samples):
        seen.append(samples)
        return bots.passive(view, True)

    monkeypatch.setattr(bots, "choose", passive_only)
    session.advance(t, stop_at_hero=False, samples=2)
    assert len(seen) > 12
    assert set(seen) == {2}


def test_current_players_pending_action_and_stakes_shape_preflop():
    t, s = table(6)
    v = replace(session.bot_view(t, s), cards=("9h", "8h"), position="HJ")
    m = model()
    m["traits"].update(looseness=1.3, pfr=0.8)
    full = replace(
        v, players=9, players_behind=8, opponents=tuple(bots.Opponent(i) for i in range(1, 9))
    )
    folded = replace(full, players_behind=1, opponents=(bots.Opponent(1),))
    short = replace(v, players=3, players_behind=2, opponents=(bots.Opponent(1), bots.Opponent(2)))

    def participation(view):
        return sum(
            bots.choose(view, copy.deepcopy(m), Random(i))["kind"] != "fold" for i in range(1000)
        )

    assert participation(folded) > participation(full) + 200
    assert participation(short) > participation(full) + 200
    # Absolute denominations do not invent a bankroll; equal BB depth and price play alike.
    scaled = replace(
        v,
        stack=v.stack * 5,
        effective_stack=v.effective_stack * 5,
        own_bet=v.own_bet * 5,
        pot=v.pot * 5,
        big_blind=v.big_blind * 5,
        starting_stack=v.starting_stack * 5,
        committed=v.committed * 5,
        legal=LegalActions(
            fold=True,
            call=(v.legal.call or 0) * 5,
            min_raise_to=v.legal.min_raise_to * 5,
            max_raise_to=v.legal.max_raise_to * 5,
        ),
    )
    for i in range(50):
        a = bots.choose(v, copy.deepcopy(m), Random(i))
        b = bots.choose(scaled, copy.deepcopy(m), Random(i))
        assert a["kind"] == b["kind"]
        if a["kind"] == "raise_to":
            assert abs(b["amount"] - 5 * a["amount"]) <= 3


def test_spr_multiway_barrels_commitment_and_all_in_fold_equity(monkeypatch):
    t, s = table(3)
    v = replace(
        session.bot_view(t, s),
        board=("2c", "7d", "Jh"),
        pot=1000,
        cards=("Ah", "Qh"),
        own_bet=0,
        legal=LegalActions(check=True, min_raise_to=20, max_raise_to=6000),
        opponents=(bots.Opponent(1, stack=6000),),
        effective_stack=6000,
        stack=6000,
        committed=0,
        starting_stack=6000,
        actions=(),
        fold_estimate=0.6,
    )
    m = model()
    m["traits"].update(aggression=0.8, sticky=0, sizing_tell=0)
    monkeypatch.setattr(bots, "equity", lambda *args: 0.58)

    def bets(view):
        return sum(
            bots.choose(view, copy.deepcopy(m), Random(i))["kind"] == "raise_to"
            for i in range(1200)
        )

    assert bets(replace(v, effective_stack=500, stack=500)) > bets(v) + 100
    crowded = replace(v, opponents=tuple(bots.Opponent(i, stack=6000) for i in range(1, 5)))
    assert bets(v) > bets(crowded) + 100
    facing = replace(
        v,
        board=("2c", "7d", "Jh", "Qs", "3c"),
        legal=LegalActions(fold=True, call=700),
        actions=((1, 3, "raise_to", 700),),
    )
    monkeypatch.setattr(bots, "equity", lambda *args: 0.52)

    def calls(view):
        return sum(
            bots.choose(view, copy.deepcopy(m), Random(i))["kind"] == "call" for i in range(1200)
        )

    barrels = replace(
        facing, actions=((1, 1, "raise_to", 200), (1, 2, "raise_to", 400), (1, 3, "raise_to", 700))
    )
    assert calls(facing) > calls(barrels) + 50
    invested = replace(facing, committed=4500, starting_stack=6000)
    assert calls(invested) > calls(facing) + 50
    monkeypatch.setattr(bots, "equity", lambda *args: 0.05)
    m["traits"].update(flop_bluff=0.5, turn_bluff=0.5, river_bluff=0.5)
    all_in = replace(
        v, opponents=(bots.Opponent(1, stack=0), bots.Opponent(2, stack=6000)), side_pot=0
    )
    side_pot = replace(all_in, side_pot=800)
    assert bets(all_in) < 10
    assert bets(side_pot) > bets(all_in) + 100


def test_projection_uses_public_stack_commitments_and_pending_players():
    t, s = table(3)
    v = session.bot_view(t, s)
    assert v.players_behind == 2
    assert v.starting_stack == 1000
    assert v.committed == 0
    act(t, s, "raise_to", 60)
    v = session.bot_view(t, s)
    assert v.players_behind == 1
    assert v.committed == 10
    assert next(o for o in v.opponents if o.seat == 0).stack == 940
    act(t, s, "fold")
    v = session.bot_view(t, s)
    assert len(v.opponents) == 1 and v.players == 3
    assert v.players_behind == 0
    assert v.committed == 20
