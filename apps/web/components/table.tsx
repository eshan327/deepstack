import type { CSSProperties } from "react";
import { money, type SeatView, type TableView } from "@/lib/api";

const names: Record<string, string> = {
  c: "clubs",
  d: "diamonds",
  h: "hearts",
  s: "spades",
};

function Suit({
  suit,
  x,
  y,
  size,
}: {
  suit: string;
  x: number;
  y: number;
  size: number;
}) {
  return (
    <svg
      x={x}
      y={y}
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="currentColor"
    >
      {suit === "c" ? (
        <>
          <circle cx="50" cy="25" r="21" />
          <circle cx="27" cy="55" r="21" />
          <circle cx="73" cy="55" r="21" />
          <path d="M43 49h14c-1 20 1 31 9 43H34c8-12 10-23 9-43Z" />
        </>
      ) : (
        <path
          d={
            suit === "h"
              ? "M50 91C39 78 6 57 6 31 6 7 34 0 50 23 66 0 94 7 94 31 94 57 61 78 50 91Z"
              : suit === "d"
                ? "M50 3 83 50 50 97 17 50Z"
                : "M50 3C39 20 6 43 6 63c0 23 28 30 39 9-1 9-4 15-11 21h32c-7-6-10-12-11-21 11 21 39 14 39-9C94 43 61 20 50 3Z"
          }
        />
      )}
    </svg>
  );
}

export function Card({
  card,
  back = false,
  small = false,
  order = 0,
}: {
  card?: string;
  back?: boolean;
  small?: boolean;
  order?: number;
}) {
  const suit = card?.[1] || "s";
  const rank = card?.[0] === "T" ? "10" : card?.[0];
  return (
    <div
      className={`playing-card ${back ? "card-back" : ""} ${small ? "card-small" : ""} suit-${suit}`}
      style={{ "--card-order": order } as CSSProperties}
      role="img"
      data-card={back ? "back" : card}
      aria-label={back ? "Face-down card" : `${rank} of ${names[suit]}`}
    >
      {back && (
        <svg className="card-back-emblem" viewBox="0 0 100 100" aria-hidden="true">
          <Suit suit="s" x={0} y={0} size={100} />
        </svg>
      )}
      {!back && (
        <svg className="card-face" viewBox="0 0 70 100" aria-hidden="true">
          {small ? (
            <>
              <text x="8" y="37" fontSize={rank === "10" ? 29 : 33}>
                {rank}
              </text>
              <Suit suit={suit} x={32} y={57} size={30} />
            </>
          ) : (
            <>
              <g>
                <text x="8" y="25" fontSize={rank === "10" ? 20 : 23}>
                  {rank}
                </text>
                <Suit suit={suit} x={9} y={29} size={12} />
              </g>
              <Suit suit={suit} x={23} y={38} size={24} />
              <g transform="rotate(180 35 50)">
                <text x="8" y="25" fontSize={rank === "10" ? 20 : 23}>
                  {rank}
                </text>
                <Suit suit={suit} x={9} y={29} size={12} />
              </g>
            </>
          )}
        </svg>
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
  dealt,
}: {
  player: SeatView;
  actor: boolean;
  latest: boolean;
  hero: boolean;
  style: CSSProperties;
  onSelect: (n: number) => void;
  bb?: number;
  complete: boolean;
  dealt: boolean;
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
        ) : p.in_hand && !complete && dealt ? (
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
  dealtSeats,
}: {
  view: TableView | null;
  bb?: number;
  fourColor: boolean;
  onSelect: (n: number) => void;
  replay?: boolean;
  latestSeat?: number | null;
  eventKind?: string;
  dealtSeats?: number[];
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
                  <Card
                    key={view.board[i]}
                    card={view.board[i]}
                    order={i < 3 ? i : 0}
                  />
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
            const horizontal = Math.cos(angle);
            const vertical = Math.sin(angle);
            const upperSide =
              vertical < -0.25 && Math.abs(horizontal) > 0.8 && count > 3;
            const style = {
              "--seat-x": `${50 + 40 * Math.cos(angle)}%`,
              "--seat-y": `${48 + 40 * Math.sin(angle)}%`,
              "--wager-x":
                Math.abs(horizontal) < 0.2
                  ? "clamp(130px, 12cqw, 140px)"
                  : vertical < -0.25 && !upperSide
                    ? `${Math.sign(horizontal) * 30}px`
                    : `calc(${-Math.sign(horizontal)} * clamp(115px, 12cqw, 135px))`,
              "--wager-y":
                Math.abs(horizontal) < 0.2
                  ? "35px"
                  : upperSide
                    ? "20px"
                    : vertical < -0.25
                      ? "55px"
                      : `${-vertical * (Math.abs(vertical) < 0.25 ? 85 : 45)}px`,
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
                dealt={!dealtSeats || dealtSeats.includes(p.seat)}
              />
            );
          })}
        </>
      )}
    </section>
  );
}
