"""Private identities and imperfect memories. Inputs are public evidence and own results only."""

from dataclasses import asdict, dataclass, replace
from math import log
from random import Random

from pokerkit import StandardHighHand


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class Traits:
    looseness: float
    pfr: float
    aggression: float
    sticky: float
    flop_bluff: float
    turn_bluff: float
    river_bluff: float
    fold_three: float
    open_size: float
    bet_size: float
    size_noise: float
    sizing_tell: float
    tilt_sensitivity: float
    fatigue_rate: float
    attentiveness: float


def sample(field: str, rng: Random) -> dict:
    # Independent overlapping clusters, with no cluster/style retained on the identity.
    loose = rng.random() < 0.6
    aggressive = rng.random() < 0.4
    looseness_shift, aggression_shift = {
        "balanced": (0.0, 0.0),
        "soft": (0.25, -0.14),
        "tough": (-0.15, 0.16),
    }[field]
    looseness = clamp(rng.gauss(1.55 if loose else 0.8, 0.3) + looseness_shift, 0.4, 2.4)
    aggression = clamp(rng.gauss(0.75 if aggressive else 0.3, 0.2) + aggression_shift, 0.05, 0.95)
    traits = Traits(
        looseness=looseness,
        pfr=clamp(rng.gauss(0.35 + 0.6 * aggression, 0.2), 0.05, 0.98),
        aggression=aggression,
        sticky=clamp(rng.gauss(0.07 if loose else -0.02, 0.08), -0.12, 0.26),
        flop_bluff=clamp(rng.gauss(0.06 + 0.18 * aggression, 0.08), 0.005, 0.5),
        turn_bluff=clamp(rng.gauss(0.04 + 0.15 * aggression, 0.07), 0.005, 0.45),
        river_bluff=clamp(rng.gauss(0.02 + 0.14 * aggression, 0.07), 0.005, 0.4),
        fold_three=clamp(rng.gauss(0.65 - 0.15 * looseness, 0.18), 0.05, 0.95),
        open_size=clamp(rng.gauss(3.1, 0.7), 2.0, 6.0),
        bet_size=clamp(rng.gauss(0.65, 0.24), 0.2, 1.6),
        size_noise=rng.uniform(0.1, 0.45),
        sizing_tell=clamp(rng.gauss(0, 0.28), -0.6, 0.6),
        tilt_sensitivity=rng.betavariate(1.5, 1.5),
        fatigue_rate=rng.uniform(0.001, 0.012),
        attentiveness=rng.betavariate(1.4, 1.4),
    )
    return {
        "traits": asdict(traits),
        "state": {
            "tilt": 0.0,
            "confidence": 0.0,
            "fatigue": 0.0,
            "lock": 0.0,
            "hands": 0,
            "own_equity": None,
        },
        "reads": {},
    }


def effective(model: dict, depth: float) -> Traits:
    p = Traits(**model["traits"])
    s = model["state"]
    tilt = s["tilt"] * p.tilt_sensitivity
    speculation = clamp(log(max(1, depth) / 80), -1.0, 1.0)
    return replace(
        p,
        looseness=clamp(
            p.looseness + 0.55 * tilt + 0.22 * s["fatigue"] + 0.12 * speculation - 0.65 * s["lock"],
            0.35,
            2.6,
        ),
        pfr=clamp(p.pfr + 0.15 * tilt + 0.1 * s["confidence"] - 0.2 * s["lock"]),
        aggression=clamp(
            p.aggression + 0.25 * tilt + 0.12 * s["confidence"] - 0.35 * s["lock"], 0.03, 0.98
        ),
        sticky=clamp(p.sticky + 0.12 * tilt - 0.1 * s["lock"], -0.16, 0.35),
        flop_bluff=clamp(p.flop_bluff * (1 + tilt + s["fatigue"]) * (1 - s["lock"])),
        turn_bluff=clamp(p.turn_bluff * (1 + tilt + s["fatigue"]) * (1 - s["lock"])),
        river_bluff=clamp(p.river_bluff * (1 + tilt + s["fatigue"]) * (1 - s["lock"])),
        fold_three=clamp(p.fold_three - 0.2 * tilt + 0.2 * s["lock"]),
    )


PRIORS = {
    "vpip": 0.3,
    "pfr": 0.16,
    "three_bet": 0.07,
    "fold_cbet": 0.45,
    "bluff": 0.18,
    "value": 0.65,
}


def read(model: dict, identity: str, metric: str) -> float:
    memory = model["reads"].get(identity, {}).get(metric)
    if memory is None:
        return PRIORS[metric]
    strength = memory["weight"] / (6 + memory["weight"])
    return PRIORS[metric] + strength * (memory["mean"] - PRIORS[metric])


def evidence(actions: list, players: list[int], shown: dict, board: list[str]) -> dict:
    """One hand of public opportunities; never infer a bluff from mucked cards or results."""
    result = {seat: {"vpip": 0, "pfr": 0} for seat in players}
    raises, raiser, cbetter = 0, None, None
    responded = set()
    flop_bet = False
    for seat, street, kind, amount in actions:
        obs = result[seat]
        if street == 0:
            if raises == 1 and seat != raiser and seat not in responded:
                obs["three_bet"] = int(kind == "raise_to")
                responded.add(seat)
            if kind in ("call", "raise_to") and amount:
                obs["vpip"] = 1
            if kind == "raise_to":
                obs["pfr"] = 1
                raises += 1
                raiser = seat
        elif street == 1:
            if cbetter is not None and seat != cbetter:
                obs.setdefault("fold_cbet", int(kind == "fold"))
                if kind == "raise_to":
                    cbetter = None
            if kind == "raise_to" and not flop_bet:
                flop_bet = True
                if seat == raiser:
                    cbetter = seat
    for seat in players:
        cards = shown.get(str(seat), [])
        aggressive_streets = {
            a[1] for a in actions if a[0] == seat and a[2] == "raise_to" and a[1] > 0
        }
        if len(cards) != 2:
            continue
        for street in sorted(aggressive_streets):
            street_board = board[: street + 2]
            if len(street_board) != street + 2:
                continue
            hand = StandardHighHand.from_game("".join(cards + street_board))
            # shortcut: classify shown high-card bets as bluffs; add draw reads if finer tells are needed.
            label = hand.entry.label.value
            plays_board = len(street_board) == 5 and hand == StandardHighHand.from_game(
                "".join(street_board)
            )
            if label == "High card" or plays_board:
                result[seat]["bluff"] = 1
                result[seat]["value"] = 0
            elif label not in ("One pair",):
                result[seat]["bluff"] = 0
                result[seat]["value"] = 1
    return result


def observe(model: dict, observations: dict[str, dict], rng: Random):
    attention = model["traits"]["attentiveness"]
    for memory in model["reads"].values():
        for metric in memory.values():
            metric["weight"] *= 0.97
    for identity, values in observations.items():
        memory = model["reads"].setdefault(identity, {})
        for key, value in values.items():
            if rng.random() > 0.08 + 0.92 * attention:
                continue
            noisy = clamp(value + rng.gauss(0, 0.35 * (1 - attention)))
            metric = memory.setdefault(key, {"mean": PRIORS[key], "first": noisy, "weight": 0.0})
            # Contradictory evidence moves an inattentive player's first impression more slowly.
            confirmation = 1 if abs(noisy - metric["first"]) < 0.5 else 0.45 + 0.4 * attention
            weight = (0.12 + 0.88 * attention) * confirmation
            rate = weight / (3 + metric["weight"])
            metric["mean"] += rate * (0.8 * noisy + 0.2 * metric["first"] - metric["mean"])
            metric["weight"] = min(35.0, metric["weight"] + weight)


def finish(
    model: dict,
    delta: int,
    starting_stack: int,
    bb: int,
    played: bool,
    voluntary: bool,
    rng: Random,
):
    p, s = model["traits"], model["state"]
    s["tilt"] *= 0.8
    s["confidence"] *= 0.85
    s["lock"] *= 0.88
    if played:
        size = max(20 * bb, starting_stack * 0.2)
        loss, win = clamp(-delta / size - 0.3), clamp(delta / size - 0.3)
        disappointment = max(0.0, (s["own_equity"] or 0) - 0.65) if delta < 0 else 0
        s["tilt"] = clamp(s["tilt"] + p["tilt_sensitivity"] * (loss + 1.5 * disappointment))
        s["confidence"] = clamp(s["confidence"] + win * 0.7)
        if win > 0 and rng.random() < p["tilt_sensitivity"] * win * 0.4:
            s["lock"] = max(s["lock"], win)
        s["fatigue"] = clamp(s["fatigue"] + p["fatigue_rate"] * (1 if voluntary else 1.7))
        s["hands"] += 1
    else:
        s["fatigue"] *= 0.9
    s["own_equity"] = None
