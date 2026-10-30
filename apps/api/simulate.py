"""Run: uv run python simulate.py --hands 1200 --seed 20261029."""

import argparse
import json
from collections import defaultdict
from random import Random
from time import perf_counter

from deepstack import session
from deepstack.schemas import Observations, TableConfig


def run(hands: int, seed: int, samples: int, trace: bool = False):
    totals = defaultdict(lambda: Observations().model_dump())
    names = {}
    started = perf_counter()
    rng = Random(seed)
    t = None
    last_players = None
    for number in range(hands):
        players = 2 if number < hands // 6 else 6 if number < hands * 2 // 3 else 9
        if players != last_players:
            if t:
                for seat in t["seats"]:
                    names[seat["opponent_id"]] = seat["name"]
                    for key, value in seat["observed"].items():
                        totals[seat["opponent_id"]][key] += value
            t = session.new_table("simulation", TableConfig(players=players), rng=rng)
            last_players = players
        if not t["seats"][0]["stack"]:
            t["seats"][0]["stack"] = t["seats"][0]["starting_stack"]
        session.start_hand(t, seed + number)
        state = session.advance(t, stop_at_hero=False, samples=samples)
        assert not state.status, f"Stuck seed: {seed + number}"
        assert sum(state.stacks) == sum(t["hand"]["stacks"])
        assert all(stack >= 0 for stack in state.stacks)
        cards = t["hand"]["deck"]
        assert len(cards) == len(set(cards)) == 52
        assert len(t["hand"]["commands"]) < 5000
        if trace:
            print(
                json.dumps(
                    {
                        "seed": seed + number,
                        "board": session.engine.view(t, state).board,
                        "actions": t["hand"]["public_actions"],
                        "stacks": state.stacks,
                    }
                )
            )
        if (number + 1) % 100 == 0:
            print(f"{number + 1}/{hands} hands; {perf_counter() - started:.1f}s", flush=True)
    report = {}
    for seat in t["seats"]:
        names[seat["opponent_id"]] = seat["name"]
        for key, value in seat["observed"].items():
            totals[seat["opponent_id"]][key] += value
    for identity, stats in totals.items():
        assert stats["pfr"] <= stats["vpip"] <= stats["hands"]
        assert stats["three_bet"] <= stats["three_bet_opportunities"]
        report[identity] = {
            "name": names[identity],
            **stats,
            "VPIP%": round(100 * stats["vpip"] / stats["hands"], 1),
            "PFR%": round(100 * stats["pfr"] / stats["hands"], 1),
        }
    print(
        json.dumps(
            {
                "hands": hands,
                "seed": seed,
                "samples": samples,
                "seconds": round(perf_counter() - started, 2),
                "players": report,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hands", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument(
        "--trace", action="store_true", help="Print reproducible hand actions and runouts"
    )
    args = parser.parse_args()
    if args.hands < 1 or args.samples < 1:
        parser.error("hands and samples must be positive")
    run(args.hands, args.seed, args.samples, args.trace)
