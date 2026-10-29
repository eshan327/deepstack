"""Original weighted ranges and bounded, imperfect cash-game policies. No hidden state input."""

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from random import Random

from pokerkit import Card, Deck, StandardHighHand, parse_range

from .schemas import LegalActions


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    looseness: float
    aggression: float
    sticky: float
    limp: float
    river_bluff: float


PROFILES = (
    Profile("mara", "Mara", 0.94, 0.70, 0.00, 0.03, 0.08),
    Profile("theo", "Theo", 1.25, 0.88, 0.02, 0.02, 0.16),
    Profile("nora", "Nora", 0.80, 0.55, -0.03, 0.04, 0.04),
    Profile("eli", "Eli", 1.65, 0.32, 0.13, 0.74, 0.02),
    Profile("jules", "Jules", 1.55, 0.75, 0.08, 0.38, 0.10),
    Profile("iris", "Iris", 0.76, 0.36, 0.05, 0.30, 0.015),
    Profile("owen", "Owen", 1.35, 0.44, 0.16, 0.59, 0.035),
    Profile("remy", "Remy", 1.12, 0.80, -0.01, 0.05, 0.13),
)
PROFILE_BY_KEY = {p.key: p for p in PROFILES}
FIELD_ORDER = {
    "balanced": [3, 4, 0, 1, 2, 5, 6, 7],
    "soft": [3, 6, 4, 0, 1, 5, 2, 7],
    "tough": [1, 7, 0, 2, 3, 5, 4, 6],
}

# Original hand groups, not copied solver charts; weights and position determine actions.
GROUP_TEXT = (
    "JJ+,AKs,AKo",
    "77-TT,ATs,AJs,AQs,KJs,KQs,QJs,AJo,AQo,KQo",
    "55-66,A8s,A9s,KTs,QTs,JTs,T9s,ATo",
    "22-44,A2s,A3s,A4s,A5s,A6s,A7s,K8s,K9s,Q9s,J9s,98s,87s,76s,A8o,A9o,KTo,KJo,QTo,QJo,JTo",
    "K2s,K3s,K4s,K5s,K6s,K7s,Q6s,Q7s,Q8s,J7s,J8s,T7s,T8s,97s,86s,65s,54s,A2o,A3o,A4o,A5o,A6o,A7o,K8o,K9o,Q9o,J9o,T9o,98o",
)
GROUPS = tuple(frozenset(frozenset(combo) for combo in parse_range(text)) for text in GROUP_TEXT)
ALL_COMBOS = tuple(tuple(c) for c in combinations(Deck.STANDARD, 2))


def group(cards) -> int:
    combo = frozenset(cards)
    return next((i for i, pool in enumerate(GROUPS) if combo in pool), 5)


@dataclass(frozen=True)
class BotView:
    cards: tuple[str, ...]
    board: tuple[str, ...]
    seat: int
    position: str
    players: int
    stack: int
    effective_stack: int
    own_bet: int
    pot: int
    big_blind: int
    legal: LegalActions
    opponents: tuple[tuple[int, int, int], ...]  # public seat, observed hands, VPIP
    actions: tuple[tuple[int, int, str, int], ...]  # seat, street, action, amount
    in_position: bool
    fold_estimate: float


def preflop(v: BotView, p: Profile, rng: Random) -> dict:
    g = group(tuple(Card.parse("".join(v.cards))))
    raises = [a for a in v.actions if a[1] == 0 and a[2] == "raise_to"]
    late = v.position in ("BTN", "CO") or v.players <= 3
    blind = v.position in ("SB", "BB")
    limpers = sum(a[1] == 0 and a[2] == "call" for a in v.actions) if not raises else 0
    weights = [1.0, 1.0, 0.75, 0.32, 0.04, 0.01]
    if late:
        weights = [1.0, 1.0, 1.0, 0.90, 0.25, 0.015]
    if blind and v.players <= 4:
        weights = [1.0, 1.0, 0.90, 0.72, 0.22, 0.025]
    if p.limp >= 0.3:
        weights = [1.0, 1.0, 0.70, 0.55, 0.22, 0.06]
    elif p.aggression >= 0.78:
        weights[3] += 0.12
        weights[4] += 0.08
    interest = min(1.0, weights[g] * p.looseness)
    call = v.legal.call or 0
    price = call / max(1, v.pot + call)
    depth = v.effective_stack / v.big_blind
    if not raises:
        if v.legal.check and rng.random() > interest * p.aggression:
            return {"kind": "check"}
        if rng.random() < interest:
            if p.limp > rng.random() and g > 0 and call <= v.big_blind:
                return {"kind": "call"} if call else {"kind": "check"}
            size = round(v.big_blind * (rng.choice((2.5, 3.0, 3.0, 3.5)) + limpers))
            return raise_or_call(v, size)
        return passive(v, False)
    if len(raises) >= 3:
        willing = [1.0, 0.18, 0.015, 0.0, 0.0, 0.0][g]
    elif len(raises) == 2:
        willing = [1.0, 0.47, 0.15, 0.10 if depth > 120 else 0.02, 0.01, 0.0][g]
    else:
        willing = [1.0, 0.92, 0.70, 0.48 if blind or late else 0.28, 0.16, 0.01][g]
    if call > v.effective_stack * 0.28 and g > 1:
        willing *= 0.35
    if price < 0.20 and len(raises) == 1:
        willing *= 1.20
    if g == 3 and depth < 40:
        willing *= 0.5
    willing = min(1.0, willing * (p.looseness + p.sticky))
    if rng.random() > willing:
        return passive(v, False)
    reraising = [0.85, 0.29, 0.07, 0.06 if late else 0.015, 0.0, 0.0][g] * p.aggression
    if len(raises) >= 2:
        reraising *= 0.55 if g == 0 else 0.15
    if rng.random() < reraising:
        previous = raises[-1][3]
        factor = 3.1 if late else 3.7
        if len(raises) > 1:
            factor = 2.3
        return raise_or_call(v, round(previous * factor))
    return passive(v, True)


def passive(v: BotView, call: bool) -> dict:
    if v.legal.check:
        return {"kind": "check"}
    return {"kind": "call"} if call and v.legal.call is not None else {"kind": "fold"}


def raise_or_call(v: BotView, amount: int) -> dict:
    low, high = v.legal.min_raise_to, v.legal.max_raise_to
    if low is None or high is None:
        return passive(v, True)
    return {"kind": "raise_to", "amount": max(low, min(high, amount))}


@lru_cache(maxsize=32768)
def evaluate(cards: tuple[str, ...]):
    return StandardHighHand.from_game("".join(cards))


@lru_cache(maxsize=256)
def opponent_combos(board: tuple[str, ...], raised: bool, vpip_bucket: int, pressure: int):
    dead = set(board)
    combos, weights = [], []
    for combo in ALL_COMBOS:
        strings = tuple(repr(c) for c in combo)
        if not dead.intersection(strings):
            g = group(combo)
            weight = (
                [1.0, 0.95, 0.65, 0.35, 0.12, 0.025]
                if raised
                else [0.65, 1.0, 0.8, 0.65, 0.32, 0.08]
            )[g]
            if vpip_bucket >= 3 and g >= 3:
                weight *= 1.7
            if pressure:
                ranks = Counter(c[0] for c in strings + board)
                own_pair = any(ranks[c[0]] >= 2 for c in strings)
                trips = any(ranks[c[0]] >= 3 for c in strings)
                two_pair = own_pair and sum(n >= 2 for n in ranks.values()) >= 2
                flush = max(Counter(c[1] for c in strings + board).values()) >= 5
                rank_set = {"23456789TJQKA".index(c[0]) for c in strings + board}
                if 12 in rank_set:
                    rank_set.add(-1)
                straight = any(set(range(n, n + 5)) <= rank_set for n in range(-1, 9))
                tier = 3 if trips or flush or straight else 2 if two_pair else 1 if own_pair else 0
                weight *= (
                    [0.12, 0.9, 1.5, 2.0]
                    if pressure == 1
                    else [0.045 if len(board) == 5 else 0.15, 0.55, 1.8, 3.0]
                )[tier]
                draw = len(board) < 5 and max(Counter(c[1] for c in strings + board).values()) == 4
                if draw and not own_pair:
                    weight *= 3.0
            combos.append(strings)
            weights.append(weight)
    return combos, weights


def equity(v: BotView, rng: Random, samples: int = 64) -> float:
    known = set(v.cards + v.board)
    pools = []
    for seat, hands, vpip in v.opponents:
        raised = any(a[0] == seat and a[2] == "raise_to" for a in v.actions)
        pressure = max(
            (
                2 if a[2] == "raise_to" else 1
                for a in v.actions
                if a[0] == seat and a[1] > 0 and a[2] in ("call", "raise_to")
            ),
            default=0,
        )
        bucket = round(vpip / hands * 10) if hands >= 50 else 2
        pools.append(opponent_combos(v.board, raised, bucket, pressure))
    if not pools:
        return 1.0
    wins, accepted, attempts = 0.0, 0, 0
    deck = tuple(repr(c) for c in Deck.STANDARD)
    # Reject whole conflicting samples, preserving joint range weights and mutual card removal.
    while accepted < samples and attempts < samples * 16:
        attempts += 1
        chosen = [rng.choices(combos, weights=weights, k=1)[0] for combos, weights in pools]
        flat = [c for combo in chosen for c in combo]
        if len(set(flat)) != len(flat) or known.intersection(flat):
            continue
        remaining = [c for c in deck if c not in known and c not in flat]
        board = v.board + tuple(rng.sample(remaining, 5 - len(v.board)))
        ours = evaluate(tuple(sorted(v.cards + board)))
        others = [evaluate(tuple(sorted(combo + board))) for combo in chosen]
        best = max([ours, *others])
        if ours == best:
            wins += 1.0 / (1 + sum(h == ours for h in others))
        accepted += 1
    return wins / accepted if accepted else 0.25


def choose(v: BotView, p: Profile, rng: Random, samples: int = 64) -> dict:
    if not v.board:
        return preflop(v, p, rng)
    eq = equity(v, rng, samples)
    call = v.legal.call or 0
    price = call / max(1, v.pot + call)
    spr = v.effective_stack / max(1, v.pot)
    multiway = len(v.opponents) > 1
    ranks = "23456789TJQKA"
    own_ranks = [ranks.index(c[0]) for c in v.cards]
    board_ranks = [ranks.index(c[0]) for c in v.board]
    suits = Counter(c[1] for c in v.board + v.cards)
    flush_draw = len(v.board) < 5 and max(suits.values()) == 4
    all_ranks = set(own_ranks + board_ranks)
    straight_draw = len(v.board) < 5 and any(
        len(all_ranks.intersection(range(i, i + 5))) >= 4 for i in range(9)
    )
    draw = flush_draw or straight_draw
    wet = max(Counter(c[1] for c in v.board).values()) >= 2 or len(set(board_ranks)) < len(
        board_ranks
    )
    blocker = any(c[0] == "A" and sum(b[1] == c[1] for b in v.board) >= 2 for c in v.cards)
    threshold = 0.62 + (0.10 if multiway else 0)
    value = eq > threshold
    bluff = (p.river_bluff if len(v.board) == 5 else 0.08 + 0.16 * draw) * p.aggression
    bluff *= max(0.3, min(1.4, v.fold_estimate / 0.42))
    if v.in_position:
        bluff *= 1.15
    if multiway:
        bluff *= 0.25
    if call:
        # Large deep-stack river bets represent narrower value ranges than cheap flop stabs.
        caution = (
            0.06
            + (0.08 if multiway else 0)
            + (0.10 if len(v.board) == 5 and call > v.pot * 0.65 else 0)
        )
        margin = eq - price - caution + p.sticky
        if eq > 0.80 and rng.random() < p.aggression * 0.65:
            return raise_or_call(
                v, v.own_bet + call + round((v.pot + call) * rng.choice((0.66, 0.9, 1.0)))
            )
        if draw and spr > 1.5 and not multiway and rng.random() < bluff * 0.45:
            return raise_or_call(v, v.own_bet + call + round((v.pot + call) * 0.7))
        return passive(v, margin > rng.uniform(-0.045, 0.045))
    if value and rng.random() > (0.12 + 0.12 * (1 - p.aggression)):
        size = rng.choice((0.5, 0.66, 0.75)) if wet else rng.choice((0.33, 0.5, 0.66))
        if eq > 0.85 and spr < 1.2:
            size = 1.0
        return raise_or_call(v, v.own_bet + round(v.pot * size))
    if rng.random() < bluff and (len(v.board) < 5 or blocker):
        return raise_or_call(v, v.own_bet + round(v.pot * rng.choice((0.5, 0.66, 0.75))))
    if not multiway and 0.48 < eq <= threshold and rng.random() < 0.25 * p.aggression:
        return raise_or_call(v, v.own_bet + round(v.pot * 0.33))
    return passive(v, False)
