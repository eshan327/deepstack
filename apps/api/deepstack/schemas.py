from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Chips = Annotated[int, Field(strict=True, ge=0, le=9_000_000_000_000_000)]
PositiveChips = Annotated[int, Field(strict=True, gt=0, le=9_000_000_000_000_000)]
BuyInChips = Annotated[int, Field(strict=True, gt=0, le=1_000_000_000_000)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class TableConfig(Model):
    players: int = Field(default=6, ge=2, le=9, strict=True)
    small_blind: BuyInChips = 100
    big_blind: BuyInChips = 200
    starting_stack: BuyInChips = 60000
    seat_stacks: list[BuyInChips] | None = None
    field: Literal["balanced", "soft", "tough"] = "balanced"

    @model_validator(mode="after")
    def check_table(self):
        if self.small_blind > self.big_blind:
            raise ValueError("The small blind cannot exceed the big blind.")
        if self.seat_stacks is not None and len(self.seat_stacks) != self.players:
            raise ValueError("Supply one starting stack for every seat.")
        return self


class CreateSession(Model):
    command_id: UUID
    config: TableConfig = Field(default_factory=TableConfig)
    previous_session_id: UUID | None = None


class Action(Model):
    kind: Literal["fold", "check", "call", "raise_to"]
    amount: PositiveChips | None = None

    @model_validator(mode="after")
    def check_amount(self):
        if (self.kind == "raise_to") != (self.amount is not None):
            raise ValueError("Only raise_to requires an amount.")
        return self


class Command(Model):
    command_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    kind: Literal["act", "next_hand", "advance", "top_up", "set_seat", "note", "end"]
    action: Action | None = None
    seat: int | None = Field(default=None, ge=0, le=8, strict=True)
    amount: BuyInChips | None = None
    sitting_out: bool | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def check_command(self):
        required = {
            "act": ("action",),
            "top_up": ("seat", "amount"),
            "set_seat": ("seat", "sitting_out"),
            "note": ("seat", "note"),
        }
        fields = ("action", "seat", "amount", "sitting_out", "note")
        expected = required.get(self.kind, ())
        if any((getattr(self, f) is not None) != (f in expected) for f in fields):
            raise ValueError(f"Invalid fields for {self.kind}.")
        return self


class Observations(Model):
    hands: int = 0
    vpip: int = 0
    pfr: int = 0
    three_bet: int = 0
    three_bet_opportunities: int = 0
    bets_raises: int = 0
    calls: int = 0
    folds_to_bet: int = 0
    faced_bet: int = 0


class SeatView(Model):
    seat: int
    name: str
    stack: Chips
    starting_stack: BuyInChips
    bet: Chips = 0
    cards: list[str] = Field(default_factory=list)
    in_hand: bool = False
    folded: bool = False
    sitting_out: bool = False
    dealer: bool = False
    blind: Literal["SB", "BB"] | None = None
    position: str = ""
    last_action: str = ""
    winnings: Chips = 0
    note: str = ""
    observed: Observations = Field(default_factory=Observations)


class Preset(Model):
    label: str
    amount: PositiveChips


class LegalActions(Model):
    fold: bool = False
    check: bool = False
    call: Chips | None = None
    min_raise_to: PositiveChips | None = None
    max_raise_to: PositiveChips | None = None
    presets: list[Preset] = Field(default_factory=list)


class TableView(Model):
    hand_number: int
    street: str
    board: list[str]
    pot: Chips
    pots: list[Chips]
    seats: list[SeatView]
    actor: int | None
    complete: bool
    message: str


class Snapshot(TableView):
    id: str
    version: int
    status: Literal["active", "ended"]
    config: TableConfig
    legal: LegalActions
    needs_advance: bool
    last_event_id: int
    hands_played: int
    profit: int
    buy_ins: Chips
    cash_outs: Chips
    created_at: str


class PublicEvent(Model):
    id: int
    kind: str
    text: str
    view: TableView
    seat: int | None = None
    street: str | None = None
    action: str | None = None
    amount: Chips | None = None
    to_amount: Chips | None = None


class CommandResult(Model):
    snapshot: Snapshot
    events: list[PublicEvent]


class SessionSummary(Model):
    id: str
    status: str
    hands: int
    profit: int
    created_at: str
    config: TableConfig | None = None


class HandSummary(Model):
    id: str
    number: int
    board: list[str]
    hero_cards: list[str]
    profit: int
    pot: Chips
    created_at: str
    session_id: str = ""
    position: str = ""
    big_blind: int = 200
    players: int = 6
    bookmarked: bool = False
    note: str = ""


class DecisionContext(Model):
    event_id: int
    view: TableView
    legal: LegalActions
    effective_stack: Chips
    big_blind: BuyInChips = 200
    action: Action
    side_pots: bool = False


class Replay(Model):
    hand: HandSummary
    events: list[PublicEvent]
    decisions: list[DecisionContext] = Field(default_factory=list)


class SessionList(Model):
    sessions: list[SessionSummary]
    next_cursor: str | None = None


class HandList(Model):
    hands: list[HandSummary]
    next_before: int | None


class ReviewHands(Model):
    hands: list[HandSummary]
    next_cursor: str | None


class Preferences(Model):
    bb: bool = False
    pace: Literal["deliberate", "brisk", "manual"] = "deliberate"
    fourColor: bool = False
    reducedMotion: bool = False
    sounds: bool = False
    actionLog: bool = False


class ProfileUpdate(Model):
    name: str = Field(min_length=1, max_length=32)
    preferences: Preferences = Field(default_factory=Preferences)
    table_defaults: TableConfig = Field(default_factory=TableConfig)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a name with 1–32 printable characters.")
        return value


class Profile(ProfileUpdate):
    authenticated: bool = False
    auth_available: bool = False


class Annotation(Model):
    bookmarked: bool
    note: str = Field(default="", max_length=2000)


class AnalysisRequest(Model):
    decision: int = Field(ge=0, strict=True)
    ranges: dict[int, str] = Field(default_factory=dict, max_length=8)

    @field_validator("ranges")
    @classmethod
    def bounded_ranges(cls, value):
        if any(seat < 1 or seat > 8 or len(raw) > 1000 for seat, raw in value.items()):
            raise ValueError("Use at most 1000 range characters per opponent.")
        return value


class AnalysisResult(Model):
    equity: float
    uncertainty: float
    samples: int
    call_threshold: float | None
    call_amount: Chips
    pot: Chips
    effective_stack: Chips
    ranges: dict[int, str]
    explanation: str


class RangeRequest(Model):
    range: str = Field(min_length=1, max_length=1000)


class RangeExpansion(Model):
    hands: list[str]


class GuestResult(Model):
    ready: bool


class LedgerEntry(Model):
    id: int
    seat: int
    kind: str
    amount: int
    created_at: str


class LedgerList(Model):
    entries: list[LedgerEntry]
    next_before: int | None
