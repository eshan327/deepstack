"""PokerKit translates poker rules; this module translates seats and safe presentation."""

from collections import deque
from random import Random, SystemRandom
from uuid import uuid4

from pokerkit import Card, Deck, Mode, NoLimitTexasHoldem

from .schemas import LegalActions, Preset, TableView

ENGINE_VERSION = "pokerkit-0.7.7/v1"


def create_hand(table: dict, seed: int | None = None) -> dict:
    active = [s["seat"] for s in table["seats"] if s["stack"] > 0 and not s["sitting_out"]]
    if 0 not in active or len(active) < 2:
        raise ValueError("Sit in with a funded opponent to deal the next hand.")
    previous = table["button"]
    button = next((s for s in active if s > previous), active[0])
    # PokerKit indexes the BB first and button/SB last heads-up; otherwise SB first.
    ordered = sorted(active, key=lambda s: (s - button - 1) % len(table["seats"]))
    deck = list(Deck.STANDARD)
    (Random(seed) if seed is not None else SystemRandom()).shuffle(deck)
    table["button"] = button
    table["hand_number"] += 1
    hand = {
        "id": str(uuid4()),
        "engine": ENGINE_VERSION,
        "mapping": ordered,
        "stacks": [table["seats"][s]["stack"] for s in ordered],
        "deck": [repr(c) for c in deck],
        "commands": [],
        "events": [],
        "shown": {},
        "hero_cards": [],
        "last": {},
        "winnings": {},
        "decision_seed": seed if seed is not None else SystemRandom().getrandbits(128),
        "settled": False,
        "final_pot": 0,
        "public_actions": [],
        "seen_vpip": [],
        "seen_pfr": [],
        "seen_three": [],
        "three_opps": [],
    }
    table["hand"] = hand
    return hand


def restore(table: dict):
    hand = table["hand"]
    if hand["engine"] != ENGINE_VERSION:
        raise ValueError("This hand needs a compatible engine version. Your chips are preserved.")
    config = table["config"]
    state = NoLimitTexasHoldem.create_state(
        (),
        False,
        0,
        (config["small_blind"], config["big_blind"]),
        config["big_blind"],
        hand["stacks"],
        len(hand["mapping"]),
        mode=Mode.CASH_GAME,
    )
    state.deck_cards = deque(Card.parse("".join(hand["deck"])))
    for name, args in hand["commands"]:
        getattr(state, name)(*args)
    return state


def round_raise(amount: int, low: int, high: int, bb: int) -> int:
    amount = max(low, min(high, amount))
    # Preserve exact all-ins and sub-dollar games; normal dollar tables wager whole dollars.
    if bb < 100 or amount == high:
        return amount
    return min(high, max(((low + 99) // 100) * 100, ((amount + 50) // 100) * 100))


def legal_actions(state, bb: int) -> LegalActions:
    legal = LegalActions()
    if state.actor_index is None:
        return legal
    call = state.checking_or_calling_amount or 0
    legal.fold = call > 0 and state.can_fold()
    legal.check = state.can_check_or_call() and call == 0
    legal.call = call if call else None
    if not state.can_complete_bet_or_raise_to():
        return legal
    low = state.min_completion_betting_or_raising_to_amount
    high = state.max_completion_betting_or_raising_to_amount
    legal.min_raise_to, legal.max_raise_to = low, high
    own = state.bets[state.actor_index]
    if state.street_index == 0 and max(state.bets) <= bb:
        suggestions = [("2.5 BB", round(bb * 2.5)), ("3 BB", bb * 3), ("4 BB", bb * 4)]
    elif state.street_index == 0:
        suggestions = [
            ("Min", low),
            ("2.5×", round(max(state.bets) * 2.5)),
            ("3×", max(state.bets) * 3),
        ]
    else:
        pot_after_call = state.total_pot_amount + call
        suggestions = [
            ("Min", low),
            ("½ pot", own + call + round(pot_after_call / 2)),
            ("Pot", state.pot_completion_betting_or_raising_to_amount),
        ]
    for label, value in [*suggestions, ("All-in", high)]:
        if value is not None:
            value = round_raise(value, low, high, bb)
            if state.can_complete_bet_or_raise_to(value):
                legal.presets.append(Preset(label=label, amount=value))
    return legal


def view(table: dict, state=None) -> TableView:
    hand = table.get("hand")
    seats = []
    mapping = hand["mapping"] if hand else []
    if hand and state is None:
        state = restore(table)
    actor = mapping[state.actor_index] if state and state.actor_index is not None else None
    for seat in table["seats"]:
        number = seat["seat"]
        i = mapping.index(number) if number in mapping else None
        cards = []
        if hand:
            cards = hand["hero_cards"] if number == 0 else hand["shown"].get(str(number), [])
        blind = None
        position = ""
        if i is not None:
            if len(mapping) == 2:
                blind = "BB" if i == 0 else "SB"
                position = "BB" if i == 0 else "BTN"
            else:
                blind = "SB" if i == 0 else "BB" if i == 1 else None
                labels = ["SB", "BB"] + [
                    f"UTG+{j}" if j else "UTG" for j in range(len(mapping) - 2)
                ]
                labels[-1] = "BTN"
                if len(mapping) > 3:
                    labels[-2] = "CO"
                if len(mapping) > 4:
                    labels[-3] = "HJ"
                if len(mapping) > 6:
                    labels[-4] = "LJ"
                position = labels[i]
        seats.append(
            {
                "seat": number,
                "name": seat["name"],
                "stack": state.stacks[i]
                if i is not None and not hand["settled"]
                else seat["stack"],
                "starting_stack": seat["starting_stack"],
                "bet": state.bets[i] if i is not None else 0,
                "cards": cards,
                "in_hand": i is not None,
                "folded": (str(number) in hand["last"] and hand["last"][str(number)] == "Fold")
                if hand
                else False,
                "sitting_out": seat["sitting_out"],
                "dealer": number == table["button"],
                "blind": blind,
                "position": position,
                "last_action": hand["last"].get(str(number), "") if hand else "",
                "winnings": hand["winnings"].get(str(number), 0) if hand else 0,
                "note": seat.get("note", ""),
                "observed": seat.get("observed", {}),
            }
        )
    complete = not state.status if state else True
    board = [repr(c) for row in state.board_cards for c in row] if state else []
    street = (
        ["Preflop", "Flop", "Turn", "River"][state.street_index]
        if state and state.street_index is not None
        else "Ready"
    )
    message = "Ready"
    if state:
        if complete:
            wins = [table["seats"][int(s)]["name"] for s in hand["winnings"]]
            message = f"{' & '.join(wins)} {'wins' if len(wins) == 1 else 'win'} the pot."
        elif actor == 0:
            message = "Your turn."
        else:
            message = (
                f"{table['seats'][actor]['name']} is thinking…" if actor is not None else "Dealing…"
            )
    return TableView(
        hand_number=table["hand_number"],
        street="Complete" if state and complete else street,
        board=board,
        pot=state.total_pot_amount if state else 0,
        pots=list(state.pot_amounts) if state and state.status else [],
        seats=seats,
        actor=actor,
        complete=complete,
        message=message,
    )


def perform(table: dict, state, name: str, args: list | None = None):
    hand = table["hand"]
    args = args or []
    before_street = state.street_index
    before_bet = max(state.bets, default=0)
    before_bets = tuple(state.bets)
    had_bets = any(state.bets)
    player_action = name in ("check_or_call", "complete_bet_or_raise_to", "fold")
    before_call = state.checking_or_calling_amount if player_action else 0
    before_can_raise = state.can_complete_bet_or_raise_to() if player_action else False
    op = getattr(state, name)(*args)
    hand["commands"].append([name, args])
    seat = hand["mapping"][op.player_index] if hasattr(op, "player_index") else None
    who = table["seats"][seat]["name"] if seat is not None else ""
    text, kind = "", "action"
    if name == "deal_hole":
        if seat == 0:
            hand["hero_cards"].extend(repr(c) for c in op.cards)
        text, kind = "Cards dealt", "deal"
    elif name == "deal_board":
        text, kind = "Board: " + " ".join(repr(c) for c in op.cards), "board"
        hand["last"] = {s: a for s, a in hand["last"].items() if a == "Fold"}
    elif name == "show_or_muck_hole_cards":
        if op.hole_cards:
            hand["shown"][str(seat)] = [repr(c) for c in op.hole_cards]
            text, kind = f"{who} shows {' '.join(hand['shown'][str(seat)])}", "show"
    elif name in ("post_blind_or_straddle", "check_or_call", "complete_bet_or_raise_to", "fold"):
        amount = getattr(op, "amount", 0)
        label = (
            "Fold"
            if name == "fold"
            else "Check"
            if name == "check_or_call" and not amount
            else "Call"
            if name == "check_or_call"
            else ("Raise to" if before_bet else "Bet")
            if name == "complete_bet_or_raise_to"
            else "Blind"
        )
        hand["last"][str(seat)] = (
            label if not amount else f"{label} $" + f"{amount / 100:,.2f}".removesuffix(".00")
        )
        text = f"{who}: {hand['last'][str(seat)]}"
        if name in ("check_or_call", "complete_bet_or_raise_to", "fold"):
            action_kind = (
                "fold"
                if name == "fold"
                else "raise_to"
                if name == "complete_bet_or_raise_to"
                else "call"
                if amount
                else "check"
            )
            hand["public_actions"].append([seat, before_street, action_kind, amount])
            observed = table["seats"][seat]["observed"]
            if before_street == 0:
                raises = sum(n == "complete_bet_or_raise_to" for n, _ in hand["commands"][:-1])
                if raises == 1 and before_can_raise and seat not in hand["three_opps"]:
                    hand["three_opps"].append(seat)
                if amount and name != "fold" and seat not in hand["seen_vpip"]:
                    hand["seen_vpip"].append(seat)
                if name == "complete_bet_or_raise_to":
                    if seat not in hand["seen_pfr"]:
                        hand["seen_pfr"].append(seat)
                    if raises == 1 and seat not in hand["seen_three"]:
                        hand["seen_three"].append(seat)
            elif before_street is not None:
                if name == "complete_bet_or_raise_to":
                    observed["bets_raises"] += 1
                if name == "check_or_call" and amount:
                    observed["calls"] += 1
                if before_call:
                    observed["faced_bet"] += 1
                    observed["folds_to_bet"] += name == "fold"
    elif name == "push_chips":
        for i, amount in enumerate(op.amounts):
            if amount:
                key = str(hand["mapping"][i])
                hand["winnings"][key] = hand["winnings"].get(key, 0) + amount
        hand["final_pot"] += sum(op.amounts)
        text, kind = "Pot awarded", "award"
    elif name == "collect_bets" and had_bets:
        text, kind = "Bets collected", "collect"
    if text:
        table["event_id"] += 1
        hand["events"].append(
            {
                "id": table["event_id"],
                "kind": kind,
                "text": text,
                "view": view(table, state).model_dump(),
                "seat": seat,
                "street": ["Preflop", "Flop", "Turn", "River"][before_street]
                if before_street is not None
                else None,
                "action": (
                    "blind"
                    if name == "post_blind_or_straddle"
                    else "fold"
                    if name == "fold"
                    else "call"
                    if name == "check_or_call" and getattr(op, "amount", 0)
                    else "check"
                    if name == "check_or_call"
                    else "raise"
                    if before_bet
                    else "bet"
                )
                if name
                in ("post_blind_or_straddle", "fold", "check_or_call", "complete_bet_or_raise_to")
                else None,
                "amount": (
                    getattr(op, "amount", 0) - before_bets[op.player_index]
                    if name == "complete_bet_or_raise_to"
                    else getattr(op, "amount", None)
                ),
                "to_amount": getattr(op, "amount", None)
                if name == "complete_bet_or_raise_to"
                else None,
            }
        )
    # PokerKit includes outstanding bets in total_pot_amount, including chip-pushing phases.
    assert all(s >= 0 for s in state.stacks)
    if not state.status:
        assert sum(state.stacks) == sum(hand["stacks"])
    return op


def advance_forced(table: dict, state) -> bool:
    for check, action in (
        ("can_post_ante", "post_ante"),
        ("can_collect_bets", "collect_bets"),
        ("can_post_blind_or_straddle", "post_blind_or_straddle"),
        ("can_burn_card", "burn_card"),
        ("can_deal_hole", "deal_hole"),
        ("can_select_runout_count", "select_runout_count"),
        ("can_show_or_muck_hole_cards", "show_or_muck_hole_cards"),
        ("can_deal_board", "deal_board"),
        ("can_kill_hand", "kill_hand"),
        ("can_push_chips", "push_chips"),
        ("can_pull_chips", "pull_chips"),
    ):
        if getattr(state, check)():
            perform(table, state, action, [1] if action == "select_runout_count" else [])
            return True
    return False


def act(table: dict, state, action: dict):
    legal = legal_actions(state, table["config"]["big_blind"])
    kind, amount = action["kind"], action.get("amount")
    if kind == "fold" and legal.fold:
        perform(table, state, "fold")
    elif (kind == "check" and legal.check) or (kind == "call" and legal.call is not None):
        perform(table, state, "check_or_call")
    elif kind == "raise_to" and amount is not None and state.can_complete_bet_or_raise_to(amount):
        perform(table, state, "complete_bet_or_raise_to", [amount])
    else:
        raise ValueError("That action is no longer legal. Refresh the table and try again.")
