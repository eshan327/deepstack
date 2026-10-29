"use client";
import { useEffect, useState } from "react";
import { money, type Action, type Snapshot } from "@/lib/api";
import { Icon } from "./icons";

export default function ActionDock({
  snapshot: s,
  busy,
  bb,
  onAct,
  onNext,
  onTopUp,
  onSitIn,
  onStart,
}: {
  snapshot: Snapshot | null;
  busy: boolean;
  bb?: number;
  onAct: (action: Action) => void;
  onNext: () => void;
  onTopUp: () => void;
  onSitIn: () => void;
  onStart: () => void;
}) {
  const low = s?.legal.min_raise_to ?? 0;
  const high = s?.legal.max_raise_to ?? 0;
  const [raw, setRaw] = useState(() => (low ? String(low / 100) : ""));
  const amount = Math.round(Number(raw) * 100);
  const valid =
    /^(?:\d+|\d*\.\d{1,2})$/.test(raw) &&
    Number.isFinite(amount) &&
    Number.isSafeInteger(amount) &&
    amount >= low &&
    amount <= high;
  const ready = !!s && s.actor === 0 && !s.complete && !busy;
  const format = (n: number) => money(n, bb);

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (
        !ready ||
        event.repeat ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        target.closest(
          "input, textarea, select, button, nav, [role=dialog], [contenteditable=true]",
        ) ||
        document.querySelector("[role=dialog]") ||
        !target.closest(".play-workspace")
      )
        return;
      if (event.key.toLowerCase() === "f" && s?.legal.fold) {
        event.preventDefault();
        onAct({ kind: "fold" });
      }
      if (event.key.toLowerCase() === "c") {
        event.preventDefault();
        onAct({ kind: s?.legal.check ? "check" : "call" });
      }
      if (event.key.toLowerCase() === "r" && low && valid) {
        event.preventDefault();
        onAct({ kind: "raise_to", amount });
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, [ready, s, low, valid, amount, onAct]);

  if (!s)
    return (
      <section className="action-dock dock-waiting">
        <button className="primary" onClick={onStart} disabled={busy}>
          Start table <Icon name="arrow" />
        </button>
      </section>
    );
  if (s.status === "ended")
    return (
      <section className="action-dock dock-waiting">
        <div>
          <strong>Session complete</strong>
        </div>
        <button className="primary" onClick={onStart}>
          New table <Icon name="arrow" />
        </button>
      </section>
    );
  if (s.complete) {
    const hero = s.seats[0];
    const canDeal =
      hero.stack > 0 &&
      !hero.sitting_out &&
      s.seats.some((p) => p.seat && !p.sitting_out);
    return (
      <section className="action-dock dock-waiting">
        <div>
          <strong>{s.hand_number ? s.message : "Ready"}</strong>
        </div>
        {hero.sitting_out ? (
          <button className="primary" onClick={onSitIn} disabled={busy}>
            Sit back in
          </button>
        ) : hero.stack === 0 ? (
          <button className="primary" onClick={onTopUp} disabled={busy}>
            Rebuy
          </button>
        ) : (
          <button
            className="primary"
            onClick={onNext}
            disabled={busy || !canDeal}
          >
            {busy
              ? "Dealing…"
              : s.hand_number
                ? "Next Hand"
                : "Deal first hand"}
            <Icon name="arrow" />
          </button>
        )}
      </section>
    );
  }
  if (!ready)
    return (
      <section className="action-dock dock-waiting">
        <div>
          <strong>{busy ? "Playing…" : s.message}</strong>
        </div>
        <span className="thinking-dots">
          <i />
          <i />
          <i />
        </span>
      </section>
    );
  const setAmount = (value: number) => setRaw(String(value / 100));
  return (
    <section className="action-dock" aria-label="Betting controls">
      <div className="call-amount">
        <strong>
          {s.legal.check ? "Your move" : `${format(s.legal.call || 0)} to call`}
        </strong>
        <span>Pot {format(s.pot)}</span>
      </div>
      <div className="sizing-controls">
        <label className="amount-label">
          {s.seats[0].bet || s.legal.call || 0 ? "Raise to" : "Bet"}
          <span className="amount-input">
            <span>{"$"}</span>
            <input
              aria-label="Raise to amount"
              aria-describedby="raise-limits"
              inputMode="decimal"
              type="text"
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              disabled={!low}
              aria-invalid={!!low && !valid}
            />
          </span>
        </label>
        <div className="slider-controls">
          <div className="presets">
            {s.legal.presets.map((p, i) => (
              <button
                key={`${p.label}-${i}`}
                aria-pressed={amount === p.amount}
                onClick={() => setAmount(p.amount)}
                type="button"
              >
                {p.label}
              </button>
            ))}
          </div>
          <input
            type="range"
            aria-label="Bet size"
            aria-valuetext={money(amount || low)}
            min={low}
            max={high}
            step={1}
            value={Math.max(low, Math.min(high, amount || low))}
            onChange={(e) => setAmount(Number(e.target.value))}
            disabled={!low}
          />
          <div className="range-labels" id="raise-limits">
            <span>{low ? format(low) : "No raise available"}</span>
            <span>{high ? `${format(high)} (All-in)` : ""}</span>
          </div>
        </div>
      </div>
      <div className="action-buttons">
        <button
          className="fold-button"
          onClick={() => onAct({ kind: "fold" })}
          disabled={!s.legal.fold}
        >
          Fold
        </button>
        <button
          className="call-button"
          onClick={() => onAct({ kind: s.legal.check ? "check" : "call" })}
        >
          {s.legal.check ? "Check" : `Call ${format(s.legal.call || 0)}`}
        </button>
        <button
          className="raise-button"
          disabled={!low || !valid}
          onClick={() => onAct({ kind: "raise_to", amount })}
        >
          {s.seats[0].bet || s.legal.call || 0 ? "Raise to" : "Bet"}{" "}
          {valid ? format(amount) : "—"}
        </button>
      </div>
    </section>
  );
}
