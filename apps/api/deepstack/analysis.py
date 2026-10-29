"""Bounded review of public decisions, never of private bot state or future cards."""

from hashlib import blake2b
from math import sqrt
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
    rng = Random(
        int.from_bytes(
            blake2b(
                repr((hero.cards, view.board, sorted(ranges.items()))).encode(), digest_size=16
            ).digest()
        )
    )
    deck = tuple(repr(c) for c in Deck.STANDARD)
    count, total, squares, attempts = 0, 0.0, 0.0, 0
    deadline = monotonic() + 3
    while count < 512 and attempts < 32768 and monotonic() < deadline:
        attempts += 1
        chosen = [rng.choice(pool) for pool in pools]
        flat = [c for combo in chosen for c in combo]
        if len(set(flat)) != len(flat):
            continue
        dead = known.union(flat)
        board = tuple(view.board) + tuple(
            rng.sample([c for c in deck if c not in dead], 5 - len(view.board))
        )
        ours = evaluate(tuple(sorted(tuple(hero.cards) + board)))
        others = [evaluate(tuple(sorted(combo + board))) for combo in chosen]
        share = 1 / (1 + sum(h == ours for h in others)) if ours >= max(others) else 0
        total += share
        squares += share * share
        count += 1
    if count < 32:
        raise ValueError("These ranges have too few compatible combinations. Widen a range.")
    equity = total / count
    variance = max(0.0, (squares - count * equity * equity) / (count - 1))
    # The floor avoids false certainty from a finite Monte Carlo sample with no losses.
    uncertainty = max(1.96 * sqrt(variance / count), 3 / count)
    call = context.legal.call or 0
    threshold = call / (view.pot + call) if call and not context.side_pots else None
    explanation = (
        "Side-pot or all-in eligibility changes the price of continuing. "
        "This is showdown equity against the selected ranges; a simple full-pot call threshold "
        "does not apply."
        if context.side_pots
        else "Compare showdown equity with the immediate call threshold. Future betting, position, "
        "and equity realization still matter; this comparison does not grade your action."
        if call
        else "With no bet to call, consider position, effective stacks, and the value of checking "
        "versus betting. Showdown equity alone does not choose a bet size."
    )
    depth = context.effective_stack / context.big_blind
    details = f"From {hero.position or 'this seat'}, the effective stack was {depth:g} BB. "
    if context.action.kind == "raise_to":
        total_wager = context.action.amount
        added = total_wager - hero.bet
        details += f"Your raise-to total was ${total_wager / 100:g}, adding ${added / 100:g}"
        if view.pot:
            details += f" ({added / view.pot:.0%} of the pot before your action)"
        details += ". "
    explanation = (
        details
        + explanation
        + " Range combinations are weighted equally; changing your assumptions can change the estimate."
    )
    return AnalysisResult(
        equity=equity,
        uncertainty=uncertainty,
        samples=count,
        call_threshold=threshold,
        call_amount=call,
        pot=view.pot,
        effective_stack=context.effective_stack,
        ranges=ranges,
        explanation=explanation,
    )
