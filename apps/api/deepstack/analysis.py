"""Bounded review of public decisions, never of private bot state or future cards."""

from hashlib import blake2b
from itertools import combinations, product
from math import comb, prod, sqrt
from random import Random
from time import monotonic

from pokerkit import Deck, parse_range

from .bots import evaluate
from .schemas import AnalysisRequest, AnalysisResult, DecisionContext


def analyze(context: DecisionContext, request: AnalysisRequest) -> AnalysisResult:
    view = context.view
    hero = view.seats[0]
    opponents = [s for s in view.seats[1:] if s.in_hand and not s.folded]
    if not opponents or len(hero.cards) != 2:
        raise ValueError("This decision has no opponent range to evaluate.")
    if set(request.ranges) - {s.seat for s in opponents}:
        raise ValueError("Choose ranges only for opponents active at this decision.")
    known = set(hero.cards + view.board)
    ranges, pools = {}, []
    for seat in opponents:
        raw = request.ranges.get(seat.seat, "random").strip()
        ranges[seat.seat] = raw
        if raw.lower() == "random":
            from .bots import ALL_COMBOS

            combos = [tuple(repr(c) for c in combo) for combo in ALL_COMBOS]
        else:
            try:
                parsed = parse_range(raw)
                if any(len(combo) != 2 for combo in parsed):
                    raise ValueError()
                combos = sorted(tuple(sorted(repr(c) for c in combo)) for combo in parsed)
            except (ValueError, KeyError, IndexError, AssertionError):
                raise ValueError(f"Invalid Hold’em range for {seat.name}.") from None
        combos = [combo for combo in combos if not known.intersection(combo)]
        if not combos:
            raise ValueError(f"{seat.name}'s range conflicts with the known cards.")
        pools.append(combos)
    range_combos = {seat.seat: len(pool) for seat, pool in zip(opponents, pools)}
    missing = 5 - len(view.board)
    outcomes = prod(map(len, pools)) * comb(52 - len(known) - 2 * len(pools), missing)
    exact = outcomes <= 20000
    assignments = iter(product(*pools)) if exact else None
    rng = Random(
        int.from_bytes(
            blake2b(
                repr((hero.cards, view.board, sorted(ranges.items()))).encode(), digest_size=16
            ).digest()
        )
    )
    deck = tuple(repr(c) for c in Deck.STANDARD)
    count, total, squares, attempts = 0, 0.0, 0.0, 0
    wins, ties = 0, 0
    exhausted = False
    deadline = monotonic() + 3
    while (exact or count < 2048) and attempts < 32768 and monotonic() < deadline:
        attempts += 1
        if assignments is not None:
            chosen = next(assignments, None)
            if chosen is None:
                exhausted = True
                break
        else:
            chosen = [rng.choice(pool) for pool in pools]
        flat = [c for combo in chosen for c in combo]
        if len(set(flat)) != len(flat):
            continue
        remaining = [c for c in deck if c not in known and c not in flat]
        runouts = combinations(remaining, missing) if exact else [rng.sample(remaining, missing)]
        for runout in runouts:
            if exact and monotonic() >= deadline:
                raise ValueError("Exact evaluation timed out. Widen a range and retry.")
            board = tuple(view.board) + tuple(runout)
            ours = evaluate(tuple(sorted(tuple(hero.cards) + board)))
            others = [evaluate(tuple(sorted(combo + board))) for combo in chosen]
            tied = sum(h == ours for h in others)
            share = 1 / (1 + tied) if ours >= max(others) else 0
            wins += share == 1
            ties += 0 < share < 1
            total += share
            squares += share * share
            count += 1
    if exact and not exhausted:
        raise ValueError("Exact evaluation timed out. Widen a range and retry.")
    if not count or (not exact and count < 32):
        raise ValueError("These ranges have too few compatible combinations. Widen a range.")
    equity = total / count
    variance = max(0.0, (squares - count * equity * equity) / max(1, count - 1))
    # The floor avoids false certainty from a finite Monte Carlo sample with no losses.
    uncertainty = 0.0 if exact else max(1.96 * sqrt(variance / count), 3 / count)
    call = context.legal.call or 0
    threshold = call / (view.pot + call) if call and not context.side_pots else None
    depth = context.effective_stack / context.big_blind
    details = f"{hero.position or 'Hero'} · {depth:g} BB effective."
    if context.action.kind == "raise_to":
        total_wager = context.action.amount
        added = total_wager - hero.bet
        details += f" Raised to ${total_wager / 100:g}; ${added / 100:g} added"
        if view.pot:
            details += f" ({added / view.pot:.0%} pot)"
        details += "."
    if context.side_pots:
        details += " Side-pot call price unavailable."
    return AnalysisResult(
        equity=equity,
        method="exact" if exact else "monte_carlo",
        win=wins / count,
        tie=ties / count,
        loss=(count - wins - ties) / count,
        range_combos=range_combos,
        made_hand=evaluate(tuple(sorted(hero.cards + view.board))).entry.label.value
        if len(view.board) >= 3
        else None,
        call_ev=equity * (view.pot + call) - call if threshold is not None else None,
        spr=context.effective_stack / view.pot if view.pot else None,
        uncertainty=uncertainty,
        samples=count,
        call_threshold=threshold,
        call_amount=call,
        pot=view.pot,
        effective_stack=context.effective_stack,
        ranges=ranges,
        explanation=details,
    )
