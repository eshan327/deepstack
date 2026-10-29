import type { CSSProperties } from "react";
import { money, type SeatView, type TableView } from "@/lib/api";

const suits: Record<string, string> = { c: "♣", d: "♦", h: "♥", s: "♠" };
const names: Record<string, string> = {
  c: "clubs",
  d: "diamonds",
  h: "hearts",
  s: "spades",
};

export function Card({
  card,
  back = false,
  small = false,
}: {
  card?: string;
  back?: boolean;
  small?: boolean;
}) {
  const suit = card?.[1] || "s";
  const rank = card?.[0] === "T" ? "10" : card?.[0];
  return (
    <div
      className={`playing-card ${back ? "card-back" : ""} ${small ? "card-small" : ""} suit-${suit}`}
      role="img"
      data-card={back ? "back" : card}
      aria-label={back ? "Face-down card" : `${rank} of ${names[suit]}`}
    >
      {!back && (
        <>
          <span className="card-corner">
            {rank}
            <i>{suits[suit]}</i>
          </span>
          <span className="card-pip">{suits[suit]}</span>
          <span className="card-bottom">
            {rank}
            <i>{suits[suit]}</i>
          </span>
        </>
      )}
    </div>
  );
}

function Chips({
  amount,
  bb,
  awarded = false,
}: {
  amount: number;
  bb?: number;
  awarded?: boolean;
}) {
  return (
    <div
      className={`wager ${awarded ? "awarded" : ""}`}
      aria-label={`${awarded ? "Award" : "Wager"} ${money(amount, bb)}`}
    >
      <span className="chip-stack" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span>{money(amount, bb)}</span>
    </div>
  );
}

function Seat({
  player: p,
  actor,
  latest,
  hero,
  style,
  onSelect,
  bb,
  complete,
}: {
  player: SeatView;
  actor: boolean;
  latest: boolean;
  hero: boolean;
  style: CSSProperties;
  onSelect: (n: number) => void;
  bb?: number;
  complete: boolean;
}) {
  const status = p.sitting_out
    ? "Sitting out"
    : p.winnings
      ? `Won ${money(p.winnings, bb)}`
      : actor
        ? hero
          ? "Your turn"
          : "Thinking…"
        : p.stack === 0 && p.in_hand && !p.folded
          ? complete
            ? "Busted"
            : "All-in"
          : p.last_action;
  return (
    <div
      style={style}
      data-seat={p.seat}
      className={`seat seat-${p.seat} ${hero ? "hero-seat" : ""} ${actor ? "acting" : ""} ${latest ? "latest-action" : ""} ${p.folded || p.sitting_out ? "inactive" : ""} ${p.winnings ? "winner" : ""}`}
    >
      <div className="hole-cards" aria-hidden={!hero && p.folded}>
        {p.cards.length ? (
          p.cards.map((card, i) => (
            <Card key={`${card}-${i}`} card={card} small={!hero} />
          ))
        ) : p.in_hand && !complete ? (
          <>
            <Card back small />
            <Card back small />
          </>
        ) : null}
      </div>
      <button
        className="nameplate"
        onClick={() => onSelect(p.seat)}
        aria-label={`${p.name}, ${money(p.stack, bb)}${p.position ? `, ${p.position}` : ""}. Open player details`}
      >
        <span className="monogram" aria-hidden="true">
          {p.name[0]}
        </span>
        <span className="seat-details">
          <span className="seat-identity">
            <span className="seat-name">{p.name}</span>
            <span className="seat-position">{p.position}</span>
          </span>
          <span className="seat-stack">{money(p.stack, bb)}</span>
          <span className="seat-action">{status || "Seated"}</span>
        </span>
      </button>
      <div className="seat-markers">
        {p.dealer && (
          <span
            className="dealer"
            key={`button-${p.seat}`}
            aria-label="Dealer button"
          >
            D
          </span>
        )}
        {p.blind && (
          <span
            className="blind"
            aria-label={`${p.blind === "SB" ? "Small" : "Big"} blind`}
          >
            {p.blind}
          </span>
        )}
      </div>
      {p.bet > 0 && <Chips key={p.bet} amount={p.bet} bb={bb} />}
      {p.winnings > 0 && <Chips awarded amount={p.winnings} bb={bb} />}
    </div>
  );
}

export default function PokerTable({
  view,
  bb,
  fourColor,
  onSelect,
  replay = false,
  latestSeat,
  eventKind,
}: {
  view: TableView | null;
  bb?: number;
  fourColor: boolean;
  onSelect: (n: number) => void;
  replay?: boolean;
  latestSeat?: number | null;
  eventKind?: string;
}) {
  const count = view?.seats.length || 6;
  return (
    <section
      className={`table-stage players-${count} ${fourColor ? "four-color" : ""} ${replay ? "replay-table" : ""}`}
      data-event={eventKind}
      aria-label={replay ? "Hand replay table" : "Poker table"}
    >
      <div className="table-rail">
        <div className="table-felt" />
      </div>
      {!view ? (
        <div className="table-loading">
          <span className="loading-ring" />
          Loading table…
        </div>
      ) : (
        <>
          <div className="community" aria-label="Community cards and pots">
            <div className="pot">
              <span>
                {view.complete && view.hand_number ? "Final pot" : "Pot"}
              </span>
              <strong>
                {money(
                  view.complete
                    ? view.seats.reduce((n, p) => n + p.winnings, 0)
                    : view.pot,
                  bb,
                )}
              </strong>
            </div>
            <div className="board" aria-label="Board">
              {Array.from({ length: 5 }, (_, i) =>
                view.board[i] ? (
                  <Card key={view.board[i]} card={view.board[i]} />
                ) : (
                  <div key={`slot-${i}`} className="card-slot" />
                ),
              )}
            </div>
            {view.pots.length > 1 && (
              <div className="side-pots">
                {view.pots.map((p, i) => (
                  <span key={i}>
                    {i ? `Side ${i}` : "Main"} {money(p, bb)}
                  </span>
                ))}
              </div>
            )}
          </div>
          {view.seats.map((p, i) => {
            const angle = Math.PI / 2 + (i / count) * Math.PI * 2;
            const style = {
              "--seat-x": `${50 + 40 * Math.cos(angle)}%`,
              "--deal-order": i,
              "--seat-y": `${48 + 40 * Math.sin(angle)}%`,
              "--wager-x": `${-Math.cos(angle) * 80}px`,
              "--wager-y": `${-Math.sin(angle) * 75}px`,
              "--collect-x": `${-Math.cos(angle) * 190}px`,
              "--collect-y": `${-Math.sin(angle) * 150}px`,
            } as CSSProperties;
            return (
              <Seat
                key={p.seat}
                player={p}
                hero={i === 0}
                actor={view.actor === p.seat}
                latest={latestSeat === p.seat}
                style={style}
                onSelect={onSelect}
                bb={bb}
                complete={view.complete}
              />
            );
          })}
        </>
      )}
    </section>
  );
}
