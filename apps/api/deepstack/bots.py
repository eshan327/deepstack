"""Original weighted ranges and bounded, imperfect cash-game policies. No hidden state input."""

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations, pairwise
from math import exp, log, log1p
from random import Random

from pokerkit import Card, Deck, StandardHighHand, parse_range

from . import opponents
from .opponents import Traits, clamp
from .schemas import LegalActions

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


COMBO_GROUPS = {frozenset(repr(c) for c in combo): group(combo) for combo in ALL_COMBOS}


@dataclass(frozen=True)
class Opponent:
    seat: int
    vpip: float = 0.3
    pfr: float = 0.16
    three_bet: float = 0.07
    fold_cbet: float = 0.45
    bluff: float = 0.18
    value: float = 0.65
    cards: tuple[str, ...] = ()  # Only publicly shown cards.
    stack: int | None = None


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
    opponents: tuple[Opponent, ...]
    actions: tuple[tuple[int, int, str, int], ...]  # seat, street, action, amount
    in_position: bool
    fold_estimate: float
    starting_stack: int = 0
    committed: int = 0
    players_behind: int = 0
    side_pot: int = 0


def curve(margin: float, noise: float = 0.1) -> float:
    return 1 / (1 + exp(-clamp(margin / noise, -30, 30)))


def sizing(p: Traits, rng: Random, value: float) -> float:
    return clamp(rng.gauss(p.bet_size + p.sizing_tell * (2 * value - 1), p.size_noise), 0.15, 2.0)


def texture(board: tuple[str, ...]) -> float:
    suits = max(Counter(c[1] for c in board).values())
    ranks = sorted({"23456789TJQKA".index(c[0]) for c in board})
    connected = sum(b - a <= 2 for a, b in pairwise(ranks)) / max(1, len(ranks) - 1)
    return clamp(0.275 * (suits - 1) + 0.45 * connected)


def preflop(v: BotView, p: Traits, rng: Random) -> dict:
    cards = tuple(Card.parse("".join(v.cards)))
    g = group(cards)
    raises = [a for a in v.actions if a[1] == 0 and a[2] == "raise_to"]
    late = v.position in ("BTN", "CO") or v.players <= 3
    blind = v.position in ("SB", "BB")
    call = v.legal.call or 0
    price = call / max(1, v.pot + call)
    depth = v.effective_stack / v.big_blind
    # Continuous noisy interest, with extra speculative interest at deeper stacks.
    strength = (0.98, 0.79, 0.64, 0.46, 0.26, 0.08)[g]
    speculative = cards[0].suit == cards[1].suit or cards[0].rank == cards[1].rank
    strength += 0.06 * clamp(log(max(1, depth) / 60), -1, 1) * speculative
    raiser = next((o for o in v.opponents if raises and o.seat == raises[-1][0]), None)
    read_strength = 0.0
    if raiser:
        frequency = raiser.three_bet if len(raises) > 1 else raiser.pfr
        # A raise from a habitual nit carries more weight than one from a frequent raiser.
        read_strength = clamp((0.16 - frequency) * 0.65, -0.2, 0.1)
    cutoff = 0.56 - 0.28 * (p.looseness - 1) - 0.12 * late - 0.04 * blind
    cutoff += 0.14 * len(raises) + price * bool(raises) * 0.25 + read_strength
    cutoff -= p.sticky * bool(raises)
    cutoff += 0.018 * (v.players - 6) + 0.008 * max(0, v.players_behind - 2)
    if raises:
        last_raise = max(j for j, a in enumerate(v.actions) if a[1] == 0 and a[2] == "raise_to")
        callers = sum(a[1] == 0 and a[2] == "call" for a in v.actions[last_raise + 1 :])
        cutoff += 0.025 * callers + 0.035 * log1p(call / v.big_blind)
        cutoff += 0.13 * call / max(1, v.effective_stack)
    else:
        cutoff -= 0.025 * max(0, v.players - len(v.opponents) - 1)
    if not raises and v.opponents:
        activity = sum(o.pfr for o in v.opponents) / len(v.opponents)
        tightness = sum(0.3 - o.vpip for o in v.opponents) / len(v.opponents)
        cutoff += max(0, activity - 0.23) * 0.5 - max(0, tightness) * 0.5
    willing = curve(strength - cutoff, 0.1)
    if len(raises) >= 2:
        willing *= 1 - p.fold_three * curve(0.82 - strength, 0.08)
    if rng.random() > willing:
        return passive(v, False)
    if not raises:
        limpers = sum(a[1] == 0 and a[2] == "call" for a in v.actions)
        # The estimated field fold rate changes the appetite for stealing with weak hands.
        steal = clamp((v.fold_estimate - 0.45) * 0.6, -0.2, 0.25)
        if rng.random() < clamp(p.pfr + steal * (1 - strength)):
            size = p.open_size + limpers + p.sizing_tell * (2 * strength - 1)
            return raise_or_call(v, round(v.big_blind * max(2, rng.gauss(size, p.size_noise))))
    else:
        value_raise = curve(strength - 0.82 - max(0, read_strength), 0.08)
        bluff_raise = p.flop_bluff * v.fold_estimate * (1 - value_raise)
        if rng.random() < p.aggression * (value_raise + bluff_raise):
            factor = 2.3 if len(raises) > 1 else 3.0 if late else 3.6
            factor += p.sizing_tell * (2 * value_raise - 1)
            return raise_or_call(v, round(raises[-1][3] * max(2, rng.gauss(factor, p.size_noise))))
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
def opponent_combos(board: tuple[str, ...], raised: bool, pressure: int):
    dead = set(board)
    combos, weights, air = [], [], []
    for combo in ALL_COMBOS:
        strings = tuple(repr(c) for c in combo)
        if not dead.intersection(strings):
            g = group(combo)
            weight = (
                [1.0, 0.95, 0.65, 0.35, 0.12, 0.025]
                if raised
                else [0.65, 1.0, 0.8, 0.65, 0.32, 0.08]
            )[g]
            tier = 0
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
            air.append(tier == 0)
    return combos, weights, air


def equity(v: BotView, rng: Random, samples: int = 64) -> float:
    known = set(v.cards + v.board)
    pools = []
    for opponent in v.opponents:
        seat = opponent.seat
        raised = any(a[0] == seat and a[1] == 0 and a[2] == "raise_to" for a in v.actions)
        pressure = max(
            (
                2 if a[2] == "raise_to" else 1
                for a in v.actions
                if a[0] == seat and a[1] > 0 and a[2] in ("call", "raise_to")
            ),
            default=0,
        )
        if opponent.cards:
            pools.append(([opponent.cards], [1.0]))
            continue
        combos, base_weights, air = opponent_combos(v.board, raised, pressure)
        preflop_raises = [a for a in v.actions if a[1] == 0 and a[2] == "raise_to"]
        reraised = any(a[0] == seat for a in preflop_raises[1:])
        frequency = (
            opponent.three_bet if raised and reraised else opponent.pfr if raised else opponent.vpip
        )
        prior = 0.07 if raised and reraised else 0.16 if raised else 0.3
        width = clamp(frequency / prior, 0.25, 3.0)
        bluffiness = clamp(opponent.bluff / 0.18, 0.25, 3.0)
        value_weight = clamp(opponent.value / 0.65, 0.4, 1.6)
        # Adjust cached public-card pools continuously using this observer's private impressions.
        weights = [
            w
            * width ** (COMBO_GROUPS[frozenset(c)] / 2 - 0.5)
            * ((bluffiness if is_air else value_weight) if pressure else 1)
            for c, w, is_air in zip(combos, base_weights, air)
        ]
        pools.append((combos, weights))
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


def choose(v: BotView, model: dict, rng: Random, samples: int = 64) -> dict:
    p = opponents.effective(model, v.effective_stack / v.big_blind)
    if not v.board:
        action = preflop(v, p, rng)
        commit = (
            action.get("amount", 0) - v.own_bet
            if action["kind"] == "raise_to"
            else v.legal.call or 0
        )
        if action["kind"] != "fold" and commit > v.stack * 0.3:
            model["state"]["own_equity"] = equity(v, rng, samples)
        return action
    eq = equity(v, rng, samples)
    model["state"]["own_equity"] = eq
    call = v.legal.call or 0
    price = call / max(1, v.pot + call)
    rivals = len(v.opponents)
    spr = v.effective_stack / max(1, v.pot)
    committed = v.committed / max(1, v.starting_stack or v.stack + v.committed)
    wet = texture(v.board)
    suits = Counter(c[1] for c in v.board + v.cards)
    ranks = {"23456789TJQKA".index(c[0]) for c in v.board + v.cards}
    if 12 in ranks:
        ranks.add(-1)
    draw = len(v.board) < 5 and (
        max(suits.values()) == 4
        or any(len(ranks.intersection(range(i, i + 5))) >= 4 for i in range(-1, 9))
    )
    threshold = 0.62 + min(0.2, 0.05 * (rivals - 1)) - 0.1 * curve(1.5 - spr, 0.6)
    value = curve(eq - threshold, 0.08)
    street_bluff = (
        p.river_bluff if len(v.board) == 5 else p.turn_bluff if len(v.board) == 4 else p.flop_bluff
    )
    bluff = street_bluff * (1 + 0.8 * draw) * clamp(v.fold_estimate / 0.45, 0.3, 1.7)
    bluff *= (1.15 if v.in_position else 1) * 0.5 ** max(0, rivals - 1)
    blocker = any(c[0] == "A" and sum(b[1] == c[1] for b in v.board) >= 2 for c in v.cards)
    bluff *= 1 + 0.25 * blocker
    # An all-in player cannot fold: pure bluffs can only win a contested side pot.
    if any(o.stack == 0 for o in v.opponents):
        bluff *= clamp(v.side_pot / max(1, v.pot))
    short = sum(o.stack is not None and o.stack < v.pot for o in v.opponents)
    bluff *= 1 - 0.4 * short / max(1, rivals)
    if call:
        aggressors = {a[0] for a in v.actions if a[1] == len(v.board) - 2 and a[2] == "raise_to"}
        reads = [o for o in v.opponents if o.seat in aggressors]
        suspicion = sum(o.bluff - 0.18 + (0.65 - o.value) * 0.25 for o in reads) / max(
            1, len(reads)
        )
        street_raises = sum(a[1] == len(v.board) - 2 and a[2] == "raise_to" for a in v.actions)
        barrels = max(
            (
                len({a[1] for a in v.actions if a[0] == seat and a[1] > 0 and a[2] == "raise_to"})
                for seat in aggressors
            ),
            default=0,
        )
        caution = 0.06 + min(0.16, 0.04 * (rivals - 1))
        caution += 0.035 * max(0, street_raises - 1) + 0.025 * max(0, barrels - 1)
        caution += 0.1 * (len(v.board) == 5) * curve(call / max(1, v.pot) - 0.65, 0.15)
        caution += 0.025 * curve(spr - 6, 2) - 0.06 * committed
        continuing = curve(eq - price - caution + p.sticky + 0.2 * suspicion, 0.06)
        raising = p.aggression * (0.7 * curve(eq - 0.8, 0.06) + bluff * 0.4 * draw)
        if rng.random() < continuing:
            if rng.random() < raising:
                return raise_or_call(
                    v, v.own_bet + call + round((v.pot + call) * sizing(p, rng, value))
                )
            return passive(v, True)
        return passive(v, False)
    prior_raises = [a for a in v.actions if a[2] == "raise_to" and a[1] < len(v.board) - 2]
    initiative = bool(prior_raises and prior_raises[-1][0] == v.seat)
    continuation = 0.1 * p.aggression * initiative * (1 - wet) * v.fold_estimate
    if any(o.stack == 0 for o in v.opponents):
        continuation *= clamp(v.side_pot / max(1, v.pot))
    betting = value * (0.5 + 0.45 * p.aggression) + (1 - value) * (bluff + continuation)
    if rng.random() < betting:
        if rng.random() < value * curve(1.2 - spr, 0.25):
            return raise_or_call(v, v.own_bet + v.stack)
        size = sizing(p, rng, value) * (1 + 0.25 * wet * value)
        return raise_or_call(v, v.own_bet + round(v.pot * size))
    return passive(v, False)
