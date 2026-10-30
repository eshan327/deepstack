from datetime import UTC, datetime
from hashlib import blake2b
from random import Random, SystemRandom
from time import monotonic
from uuid import uuid4

from . import bots, engine, opponents
from .schemas import DecisionContext, Observations, Snapshot, TableConfig

NAMES = [
    "Maya",
    "Julian",
    "Noah",
    "Sora",
    "Avery",
    "Iris",
    "Miles",
    "Jun",
    "Owen",
    "Lena",
    "Alex",
    "Robin",
    "Morgan",
    "Quinn",
    "Sage",
    "Ellis",
    "Rowan",
    "Jamie",
    "Casey",
    "Taylor",
    "Drew",
    "Reese",
    "Cameron",
    "Riley",
    "Jordan",
    "Sam",
    "Blake",
    "Devon",
    "Nico",
    "Luca",
    "Remy",
    "Kai",
    "Ari",
    "Niko",
    "Emery",
    "Sidney",
    "Jules",
    "Eden",
    "Rory",
    "Sasha",
]


def new_table(
    session_id: str,
    config: TableConfig,
    memories: dict | None = None,
    hero_name: str = "You",
    *,
    rng: Random | None = None,
) -> dict:
    memories = memories or {}
    rng = rng if rng is not None else SystemRandom()
    stacks = config.seat_stacks or [config.starting_stack] * config.players
    seats = []
    names = rng.sample(
        [n for n in NAMES if n.casefold() != hero_name.casefold()], config.players - 1
    )
    for i in range(config.players):
        identity = uuid4().hex if i else "hero"
        memory = memories.get(identity, {})
        seats.append(
            {
                "seat": i,
                "name": names[i - 1] if i else hero_name,
                "opponent_id": identity,
                **({"bot": opponents.sample(config.field, rng)} if i else {}),
                "stack": stacks[i],
                "starting_stack": stacks[i],
                "sitting_out": False,
                "observed": {**Observations().model_dump(), **memory.get("observed", {})},
                "note": memory.get("note", ""),
            }
        )
    return {
        "id": session_id,
        "config": config.model_dump(),
        "seats": seats,
        "button": -1,
        "hand_number": 0,
        "hand": None,
        "event_id": 0,
        "version": 0,
        "status": "active",
        "hands_played": 0,
        "profit": 0,
        "buy_ins": stacks[0],
        "cash_outs": 0,
        "created_at": datetime.now(UTC).isoformat(),
    }


def bot_view(table: dict, state) -> bots.BotView:
    hand = table["hand"]
    i = state.actor_index
    seat = hand["mapping"][i]
    public = engine.view(table, state)
    model = table["seats"][seat].get("bot", {"reads": {}})
    rivals = tuple(
        bots.Opponent(
            seat=s.seat,
            **{
                key: opponents.read(
                    model, table["seats"][s.seat].get("opponent_id", str(s.seat)), key
                )
                for key in opponents.PRIORS
            },
            cards=tuple(hand["shown"].get(str(s.seat), [])),
            stack=s.stack,
        )
        for s in public.seats
        if s.in_hand and not s.folded and s.seat != seat
    )
    return bots.BotView(
        cards=tuple(repr(c) for c in state.hole_cards[i]),
        board=tuple(public.board),
        seat=seat,
        position=public.seats[seat].position,
        players=len(hand["mapping"]),
        stack=state.stacks[i],
        effective_stack=state.get_effective_stack(i),
        own_bet=state.bets[i],
        pot=state.total_pot_amount,
        big_blind=table["config"]["big_blind"],
        legal=engine.legal_actions(state, table["config"]["big_blind"]),
        opponents=rivals,
        actions=tuple(tuple(a) for a in hand["public_actions"]),
        in_position=i
        == max(
            j for j in state.player_indices if state.statuses[j] and (state.stacks[j] > 0 or j == i)
        ),
        fold_estimate=sum(o.fold_cbet for o in rivals if o.stack != 0) / max(1, len(rivals)),
        starting_stack=hand["stacks"][i],
        committed=max(0, hand["stacks"][i] - state.stacks[i]),
        players_behind=max(0, len(state.actor_indices) - 1),
        side_pot=sum(public.pots[1:]),
    )


def model_for(table: dict, seat: dict) -> dict:
    if "bot" not in seat:
        # Upgrade legacy private sessions only on a write; names and old profile keys play no role.
        seed = f"opponent:{table['id']}:{seat['seat']}:{seat.get('opponent_id', '')}"
        rng = Random(int.from_bytes(blake2b(seed.encode(), digest_size=16).digest()))
        seat["bot"] = opponents.sample(table["config"]["field"], rng)
    return seat["bot"]


def update_opponents(table: dict, state):
    hand = table["hand"]
    public = engine.view(table, state)
    observations = opponents.evidence(
        hand["public_actions"], hand["mapping"], hand["shown"], public.board
    )
    for seat in table["seats"]:
        if seat["seat"] == 0 and "bot" not in seat:
            continue
        model = model_for(table, seat)
        seed = f"memory:{hand['decision_seed']}:{seat['seat']}"
        rng = Random(int.from_bytes(blake2b(seed.encode(), digest_size=16).digest()))
        if seat["seat"] in hand["mapping"]:
            # A sitting-out opponent cannot watch from outside the table.
            opponents.observe(
                model,
                {
                    table["seats"][s].get("opponent_id", str(s)): obs
                    for s, obs in observations.items()
                    if s != seat["seat"]
                },
                rng,
            )
            i = hand["mapping"].index(seat["seat"])
            opponents.finish(
                model,
                state.stacks[i] - hand["stacks"][i],
                hand["stacks"][i],
                table["config"]["big_blind"],
                True,
                seat["seat"] in hand["seen_vpip"],
                rng,
            )
        else:
            opponents.finish(
                model, 0, seat["stack"], table["config"]["big_blind"], False, False, rng
            )


def settle(table: dict, state):
    hand = table["hand"]
    if hand["settled"] or state.status:
        return
    for i, seat_number in enumerate(hand["mapping"]):
        seat = table["seats"][seat_number]
        seat["stack"] = state.stacks[i]
        obs = seat["observed"]
        obs["hands"] += 1
        for field, key in (
            ("vpip", "seen_vpip"),
            ("pfr", "seen_pfr"),
            ("three_bet", "seen_three"),
            ("three_bet_opportunities", "three_opps"),
        ):
            obs[field] += seat_number in hand[key]
    update_opponents(table, state)
    hero_index = hand["mapping"].index(0)
    table["profit"] += state.stacks[hero_index] - hand["stacks"][hero_index]
    table["hands_played"] += 1
    hand["settled"] = True
    table["event_id"] += 1
    final = engine.view(table, state)
    hand["events"].append(
        {
            "id": table["event_id"],
            "kind": "complete",
            "text": final.message,
            "view": final.model_dump(),
        }
    )


def advance(table: dict, *, stop_at_hero: bool = True, samples: int = 64):
    state = engine.restore(table)
    started = monotonic()
    steps = 0
    decisions = 0
    while state.status:
        if engine.advance_forced(table, state):
            steps += 1
        elif state.actor_index is not None:
            seat = table["hand"]["mapping"][state.actor_index]
            if stop_at_hero and seat == 0:
                break
            model = model_for(table, table["seats"][seat])
            v = bot_view(table, state)
            seed = f"{table['hand']['decision_seed']}:{seat}:{len(table['hand']['commands'])}"
            rng = Random(int.from_bytes(blake2b(seed.encode(), digest_size=16).digest()))
            # shortcut: small sampling after 12 decisions; increase only if profiling leaves headroom.
            action = bots.choose(v, model, rng, samples if decisions < 12 else min(samples, 12))
            engine.act(table, state, action)
            decisions += 1
            steps += 1
        else:
            raise RuntimeError("The engine has no legal next transition.")
        # Checkpoint only between decisions; client advances without spending a human turn.
        if stop_at_hero and (monotonic() - started > 6 or steps >= 256):
            break
        if steps > 5000:
            raise RuntimeError("Hand exceeded its safety bound.")
    settle(table, state)
    return state


def start_hand(table: dict, seed: int | None = None):
    if table["hand"] and not table["hand"]["settled"]:
        raise ValueError("Finish the current hand before dealing again.")
    rebuys = []
    for seat in table["seats"][1:]:
        if seat["stack"] == 0 and not seat["sitting_out"]:
            seat["stack"] = seat["starting_stack"]
            rebuys.append((seat["seat"], seat["stack"]))
    engine.create_hand(table, seed)
    return rebuys


def snapshot(table: dict, state=None) -> Snapshot:
    if table.get("hand") and state is None:
        state = engine.restore(table)
    public = engine.view(table, state)
    pending = bool(state and state.status and public.actor != 0)
    return Snapshot(
        **public.model_dump(),
        id=table["id"],
        version=table["version"],
        status=table["status"],
        config=table["config"],
        legal=engine.legal_actions(state, table["config"]["big_blind"])
        if state and public.actor == 0 and table["status"] == "active"
        else {},
        needs_advance=pending,
        last_event_id=table["event_id"],
        hands_played=table["hands_played"],
        profit=table["profit"],
        buy_ins=table["buy_ins"],
        cash_outs=table["cash_outs"],
        created_at=table["created_at"],
    )


def command(table: dict, cmd):
    if table["status"] != "active":
        raise ValueError("This session has ended.")
    state = engine.restore(table) if table.get("hand") else None
    between = state is None or not state.status
    ledger = []
    if cmd.kind == "act":
        if (
            state is None
            or not state.status
            or state.actor_index is None
            or table["hand"]["mapping"][state.actor_index] != 0
        ):
            raise ValueError("Wait for your turn.")
        public = engine.view(table, state)
        context = DecisionContext(
            event_id=table["event_id"],
            view=public,
            legal=engine.legal_actions(state, table["config"]["big_blind"]),
            effective_stack=state.get_effective_stack(state.actor_index),
            big_blind=table["config"]["big_blind"],
            action=cmd.action,
            side_pots=len(list(state.pots)) > 1
            or any(s.in_hand and not s.folded and s.stack == 0 for s in public.seats)
            or (state.checking_or_calling_amount or 0) >= public.seats[0].stack,
        )
        engine.act(table, state, cmd.action.model_dump())
        table["hand"].setdefault("decisions", []).append(context.model_dump())
        state = advance(table)
    elif cmd.kind == "advance":
        state = advance(table) if state and state.status else state
    elif cmd.kind == "next_hand":
        ledger = [(s, "rebuy", a) for s, a in start_hand(table)]
        state = advance(table)
    elif cmd.kind == "note":
        if cmd.seat >= len(table["seats"]) or cmd.seat == 0:
            raise ValueError("Choose an opponent to save a note.")
        table["seats"][cmd.seat]["note"] = cmd.note
    elif not between:
        raise ValueError("Finish this hand before changing seats, adding chips, or cashing out.")
    elif cmd.kind in ("top_up", "set_seat"):
        if cmd.seat >= len(table["seats"]):
            raise ValueError("That seat does not exist.")
        seat = table["seats"][cmd.seat]
        if cmd.kind == "top_up":
            if seat["stack"] + cmd.amount > 1_000_000_000_000:
                raise ValueError("That top-up exceeds the table limit.")
            seat["stack"] += cmd.amount
            if cmd.seat == 0:
                table["buy_ins"] += cmd.amount
            ledger.append((cmd.seat, "top_up", cmd.amount))
        else:
            seat["sitting_out"] = cmd.sitting_out
    elif cmd.kind == "end":
        table["status"] = "ended"
        for seat in table["seats"]:
            ledger.append((seat["seat"], "cash_out", -seat["stack"]))
        table["cash_outs"] += table["seats"][0]["stack"]
    table["version"] += 1
    return state, ledger
