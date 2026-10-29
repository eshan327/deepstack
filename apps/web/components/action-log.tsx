"use client";
import { useEffect, useRef } from "react";
import { money, type PublicEvent } from "@/lib/api";
import { Card } from "./table";

export default function ActionLog({
  events,
  bb,
  selected,
  onSelect,
}: {
  events: PublicEvent[];
  bb?: number;
  selected?: number;
  onSelect?: (index: number) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!onSelect) end.current?.scrollIntoView({ block: "nearest" });
  }, [events.length, onSelect]);
  const visible = events.flatMap((event, index) =>
    event.kind === "deal" || event.kind === "collect" ? [] : [{ event, index }],
  );
  return (
    <div
      className="action-log"
      role="log"
      aria-label="Hand action log"
      aria-live="off"
    >
      {!events.length && <p className="empty-copy">No actions yet.</p>}
      {visible.map(({ event, index: i }, n) => {
        const group =
          event.kind === "board"
            ? event.view.street
            : event.street || event.view.street;
        const previous = visible[n - 1]?.event;
        const previousGroup =
          previous?.kind === "board"
            ? previous.view.street
            : previous?.street || previous?.view.street;
        const heading = group !== previousGroup && group !== "Ready";
        const player = event.seat == null ? null : event.view.seats[event.seat];
        const amount = event.to_amount ?? event.amount;
        return (
          <div key={event.id}>
            {heading && (
              <div className="log-street">
                <span>{group}</span>
                {group !== "Preflop" && (
                  <span className="mini-board">
                    {event.view.board.map((c) => (
                      <Card key={c} card={c} small />
                    ))}
                  </span>
                )}
              </div>
            )}
            {event.kind !== "board" && (
              <button
                type="button"
                disabled={!onSelect}
                onClick={() => onSelect?.(i)}
                className={`log-row ${selected === i || (!onSelect && i === events.length - 1) ? "selected" : ""}`}
              >
                <span className="log-person">
                  {player
                    ? player.name
                    : event.kind === "complete"
                      ? "Result"
                      : "Table"}
                  {player && <small>{player.position}</small>}
                </span>
                <span className="log-action">
                  {event.action
                    ? event.action === "raise"
                      ? "Raises to"
                      : event.action === "blind"
                        ? "Posts blind"
                        : `${event.action[0].toUpperCase()}${event.action.slice(1)}${["fold", "check", "call", "bet"].includes(event.action) ? "s" : ""}`
                    : event.text.replace(/^[^:]+:\s*/, "")}
                </span>
                {amount != null && amount > 0 && (
                  <span className="log-amount">{money(amount, bb)}</span>
                )}
              </button>
            )}
          </div>
        );
      })}
      <div ref={end} />
    </div>
  );
}
