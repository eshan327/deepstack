"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import {
  api,
  defaults,
  money,
  type Command,
  type LedgerList,
  type Preferences,
  type Profile,
  type PublicEvent,
  type Snapshot,
  type TableConfig,
} from "@/lib/api";
import { authClient } from "@/lib/auth-client";
import { Icon } from "./icons";
import ActionLog from "./action-log";

export type Panel = "settings" | "player" | "account" | "log" | null;
export type { Preferences } from "@/lib/api";
type Props = {
  panel: Panel;
  onClose: () => void;
  snapshot: Snapshot | null;
  selectedSeat: number;
  preferences: Preferences;
  onPreferences: (p: Preferences) => void;
  onCommand: (
    cmd: Omit<Command, "command_id" | "expected_version">,
  ) => Promise<boolean>;
  onCreate: (config: TableConfig) => Promise<void>;
  profile: Profile | null;
  onProfile: (profile: Profile) => Promise<void>;
  events: PublicEvent[];
  busy: boolean;
  onSignedOut: () => Promise<void>;
};

export default function Drawers(props: Props) {
  const titles = {
    settings: "Table settings",
    account: "Your account",
    log: "This hand",
    player: props.snapshot?.seats[props.selectedSeat]?.name || "Player",
  };
  return (
    <Dialog.Root
      open={!!props.panel}
      onOpenChange={(open) => {
        if (!open) props.onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className="drawer">
          <div className="drawer-header">
            <Dialog.Title>
              {props.panel ? titles[props.panel] : "Table"}
            </Dialog.Title>
            <Dialog.Close className="icon-button" aria-label="Close panel">
              <Icon name="close" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">
            Table configuration, account preferences, or player details.
          </Dialog.Description>
          <div className="drawer-body">
            {props.panel === "settings" && <Settings {...props} />}
            {props.panel === "account" && <Account {...props} />}
            {props.panel === "player" && <PlayerPanel {...props} />}
            {props.panel === "log" && (
              <ActionLog
                events={props.events}
                bb={
                  props.preferences.bb
                    ? props.snapshot?.config.big_blind
                    : undefined
                }
              />
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Settings({ snapshot: s, profile, onCreate, onCommand, busy }: Props) {
  const [config, setConfig] = useState<TableConfig>(
    s?.config || profile?.table_defaults || defaults,
  );
  const [individual, setIndividual] = useState(!!s?.config.seat_stacks);
  const [stacks, setStacks] = useState(
    s?.config.seat_stacks ||
      Array.from({ length: 9 }, () => config.starting_stack),
  );
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const canCreate =
    !busy && (!s || s.complete || s.status === "ended") && !submitting;
  const update = (key: keyof TableConfig, value: number | string) =>
    setConfig((old) => ({ ...old, [key]: value }));
  return (
    <form
      className="table-config"
      onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        setSubmitting(true);
        try {
          await onCreate({
            ...config,
            seat_stacks: individual
              ? Array.from(
                  { length: config.players },
                  (_, i) => stacks[i] ?? config.starting_stack,
                )
              : null,
          });
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setSubmitting(false);
        }
      }}
    >
      <p className="panel-intro">Set the game you want to play.</p>
      <label className="form-label">
        Players
        <select
          value={config.players}
          onChange={(e) => update("players", Number(e.target.value))}
        >
          {Array.from({ length: 8 }, (_, i) => (
            <option value={i + 2} key={i}>
              {i + 2} players
            </option>
          ))}
        </select>
      </label>
      <fieldset>
        <legend>Blinds</legend>
        <div className="choice-row">
          {[
            [50, 100],
            [100, 200],
            [200, 500],
            [500, 1000],
          ].map(([sb, bb]) => (
            <button
              type="button"
              key={bb}
              aria-pressed={
                config.small_blind === sb && config.big_blind === bb
              }
              onClick={() =>
                setConfig((old) => ({
                  ...old,
                  small_blind: sb,
                  big_blind: bb,
                  starting_stack: Math.round(
                    (old.starting_stack / old.big_blind) * bb,
                  ),
                }))
              }
            >
              {money(sb)} / {money(bb)}
            </button>
          ))}
        </div>
        <div className="form-grid">
          {(["small_blind", "big_blind"] as const).map((key) => (
            <label className="form-label" key={key}>
              {key === "small_blind" ? "Small blind ($)" : "Big blind ($)"}
              <input
                type="number"
                min="0.01"
                max="10000000000"
                step="0.01"
                required
                value={config[key] / 100}
                onChange={(e) =>
                  update(key, Math.round(Number(e.target.value) * 100))
                }
              />
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Starting stack</legend>
        <div className="choice-row">
          {[50, 100, 200, 300].map((bb) => (
            <button
              type="button"
              key={bb}
              aria-pressed={config.starting_stack === bb * config.big_blind}
              onClick={() => update("starting_stack", bb * config.big_blind)}
            >
              {bb} BB
            </button>
          ))}
        </div>
        <div className="form-grid">
          <label className="form-label">
            Stack depth (BB)
            <input
              type="number"
              min="0.01"
              step="0.01"
              required
              value={
                Math.round((config.starting_stack / config.big_blind) * 100) /
                100
              }
              onChange={(e) =>
                update(
                  "starting_stack",
                  Math.round(Number(e.target.value) * config.big_blind),
                )
              }
            />
          </label>
          <label className="form-label">
            Starting stack ($)
            <input
              type="number"
              min="0.01"
              max="10000000000"
              step="0.01"
              required
              value={config.starting_stack / 100}
              onChange={(e) =>
                update(
                  "starting_stack",
                  Math.round(Number(e.target.value) * 100),
                )
              }
            />
          </label>
        </div>
      </fieldset>
      <label className="form-label">
        Opponent field
        <select
          value={config.field}
          onChange={(e) => update("field", e.target.value)}
        >
          <option value="balanced">Balanced cash table</option>
          <option value="soft">Softer home game</option>
          <option value="tough">Regular-heavy table</option>
        </select>
      </label>
      <label className="switch-row">
        <span>Individual starting stacks</span>
        <input
          type="checkbox"
          checked={individual}
          onChange={(e) => setIndividual(e.target.checked)}
        />
      </label>
      {individual && (
        <div className="form-grid">
          {Array.from({ length: config.players }, (_, i) => (
            <label className="form-label" key={i}>
              {i ? `Seat ${i + 1}` : "You"} ($)
              <input
                type="number"
                step="0.01"
                min="0.01"
                required
                value={(stacks[i] ?? config.starting_stack) / 100}
                onChange={(e) =>
                  setStacks((old) => {
                    const next = [...old];
                    next[i] = Math.round(Number(e.target.value) * 100);
                    return next;
                  })
                }
              />
            </label>
          ))}
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <button className="primary full" type="submit" disabled={!canCreate}>
        {submitting ? "Setting up…" : "Start table"}
        <Icon name="arrow" />
      </button>
      {!canCreate && !submitting && (
        <p className="muted small">
          Finish the current hand before changing tables.
        </p>
      )}
      {s?.status === "active" && (
        <>
          <p className="muted small">
            Starting a new table cashes out this session and keeps its history.
          </p>
          <button
            type="button"
            className="text-button full"
            disabled={!canCreate}
            onClick={() => void onCommand({ kind: "end" })}
          >
            End session & cash out
          </button>
        </>
      )}
    </form>
  );
}

function Account({
  profile,
  preferences,
  onProfile,
  onPreferences,
  onSignedOut,
}: Props) {
  const [name, setName] = useState(profile?.name || "You");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await task();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="account-identity">
        <span className="large-monogram">{name[0]}</span>
        <div>
          <strong>{profile?.name || "You"}</strong>
          <p className="muted small">
            {profile?.authenticated
              ? "History saved to your account"
              : "Guest profile"}
          </p>
        </div>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (profile)
            void run(async () => {
              await onProfile({ ...profile, name, preferences });
              setMessage(
                "Profile saved. Your table name updates with the next hand.",
              );
            });
        }}
      >
        <label className="form-label">
          Display name
          <input
            required
            maxLength={32}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <button className="secondary full" disabled={busy || !profile}>
          Save profile
        </button>
      </form>
      <h3 className="section-label">Presentation</h3>
      <label className="form-label">
        Pace
        <select
          value={preferences.pace}
          onChange={(e) =>
            onPreferences({
              ...preferences,
              pace: e.target.value as Preferences["pace"],
            })
          }
        >
          <option value="deliberate">Deliberate</option>
          <option value="brisk">Brisk</option>
          <option value="manual">Manual</option>
        </select>
      </label>
      {(
        [
          ["bb", "Show stacks in big blinds"],
          ["fourColor", "Four-color deck"],
          ["reducedMotion", "Reduce motion"],
        ] as const
      ).map(([key, label]) => (
        <label className="switch-row" key={key}>
          <span>{label}</span>
          <input
            type="checkbox"
            role="switch"
            checked={preferences[key]}
            onChange={() =>
              onPreferences({ ...preferences, [key]: !preferences[key] })
            }
          />
        </label>
      ))}
      <h3 className="section-label">
        {profile?.authenticated ? "Sign-in" : "Keep your seat"}
      </h3>
      {profile?.authenticated ? (
        <button
          className="secondary full"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              const result = await authClient.signOut();
              if (result.error) throw new Error(result.error.message);
              await onSignedOut();
            })
          }
        >
          Sign out
        </button>
      ) : (
        <>
          <p className="panel-intro">
            Save your history, notes, and preferences across devices.
          </p>
          <button
            className="secondary full"
            disabled={busy || !profile?.auth_available}
            onClick={() =>
              void run(async () => {
                const result = await authClient.signIn.social({
                  provider: "google",
                  callbackURL: window.location.origin,
                });
                if (result.error) throw new Error(result.error.message);
              })
            }
          >
            Continue with Google
          </button>
          <form
            className="email-signin"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                const result = await authClient.signIn.magicLink({
                  email,
                  callbackURL: window.location.origin,
                });
                if (result.error) throw new Error(result.error.message);
                setMessage(
                  "Check your email for a sign-in link. You can keep playing here.",
                );
              });
            }}
          >
            <label className="form-label">
              Email
              <input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <button
              className="secondary full"
              disabled={busy || !profile?.auth_available}
            >
              Send sign-in link
            </button>
          </form>
          <p className="muted small">
            {profile?.auth_available
              ? "Your guest history comes with you when you sign in."
              : "Account sign-in is awaiting provider setup. Guest play and saved history work on this browser."}
          </p>
        </>
      )}
      {message && (
        <p className="positive small" role="status">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
    </>
  );
}

function PlayerPanel({ snapshot: s, selectedSeat, onCommand, busy }: Props) {
  const p = s?.seats[selectedSeat];
  const [note, setNote] = useState(p?.note || "");
  const [topup, setTopup] = useState("100");
  const [saved, setSaved] = useState(false);
  const [ledger, setLedger] = useState<LedgerList | null>(null);
  const [error, setError] = useState("");
  if (!s || !p)
    return <p className="empty-copy">Choose a player at your table.</p>;
  const canChange = s.complete && s.status === "active" && !busy;
  const amount = Math.round(Number(topup) * 100);
  const percent = (n: number, d: number) =>
    d ? `${Math.round((100 * n) / d)}%` : "—";
  return (
    <>
      <div className="account-identity">
        <span className="large-monogram">{p.name[0]}</span>
        <div>
          <strong>{p.name}</strong>
          <p className="muted">
            {money(p.stack)} · {p.position || "Seated"}
          </p>
        </div>
      </div>
      {selectedSeat > 0 && (
        <>
          <p className="muted small">{p.observed.hands} hands observed</p>
          <dl className="summary-list">
            <div>
              <dt>VPIP</dt>
              <dd>{percent(p.observed.vpip, p.observed.hands)}</dd>
            </div>
            <div>
              <dt>Preflop raise</dt>
              <dd>{percent(p.observed.pfr, p.observed.hands)}</dd>
            </div>
            <div>
              <dt>3-bet</dt>
              <dd>
                {percent(
                  p.observed.three_bet,
                  p.observed.three_bet_opportunities,
                )}
              </dd>
            </div>
          </dl>
          <label className="form-label">
            Notes
            <textarea
              aria-label="Notes"
              maxLength={2000}
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                setSaved(false);
              }}
            />
          </label>
          <button
            className="secondary full"
            disabled={busy || s.status === "ended"}
            onClick={() =>
              void onCommand({ kind: "note", seat: selectedSeat, note }).then(
                setSaved,
              )
            }
          >
            {saved ? "Saved" : "Save note"}
          </button>
        </>
      )}
      <h3 className="section-label">Seat management</h3>
      <p className="muted small">
        Changes apply between hands. Opponents rebuy automatically.
      </p>
      <label className="form-label">
        Add chips ($)
        <input
          type="number"
          step="0.01"
          min="0.01"
          value={topup}
          onChange={(e) => setTopup(e.target.value)}
        />
      </label>
      <button
        className="secondary full"
        disabled={
          !canChange ||
          !Number.isSafeInteger(amount) ||
          amount <= 0 ||
          amount > 1e12
        }
        onClick={() =>
          void onCommand({ kind: "top_up", seat: selectedSeat, amount })
        }
      >
        Add {Number.isFinite(amount) ? money(amount) : "chips"}
      </button>
      <button
        className="text-button full"
        disabled={!canChange}
        onClick={() =>
          void onCommand({
            kind: "set_seat",
            seat: selectedSeat,
            sitting_out: !p.sitting_out,
          })
        }
      >
        {p.sitting_out ? "Sit back in" : "Sit out"}
      </button>
      {selectedSeat === 0 && (
        <>
          <h3 className="section-label">Session</h3>
          <dl className="summary-list">
            <div>
              <dt>Settled result</dt>
              <dd className={s.profit >= 0 ? "positive" : "negative"}>
                {money(s.profit)}
              </dd>
            </div>
            <div>
              <dt>Hands played</dt>
              <dd>{s.hands_played}</dd>
            </div>
            <div>
              <dt>Buy-ins & top-ups</dt>
              <dd>{money(s.buy_ins)}</dd>
            </div>
          </dl>
          <details
            onToggle={(e) => {
              if (e.currentTarget.open && !ledger)
                void api<LedgerList>(`/sessions/${s.id}/ledger`)
                  .then(setLedger)
                  .catch((err) => setError(err.message));
            }}
          >
            <summary>Chip ledger</summary>
            {ledger?.entries.map((entry) => (
              <div className="ledger-row" key={entry.id}>
                <span>
                  {s.seats[entry.seat].name} · {entry.kind.replaceAll("_", " ")}
                </span>
                <span>{money(entry.amount)}</span>
              </div>
            ))}
            {ledger?.next_before && (
              <button
                className="text-button"
                onClick={() =>
                  void api<LedgerList>(
                    `/sessions/${s.id}/ledger?before=${ledger.next_before}`,
                  )
                    .then((next) =>
                      setLedger({
                        entries: [...ledger.entries, ...next.entries],
                        next_before: next.next_before,
                      }),
                    )
                    .catch((err) => setError(err.message))
                }
              >
                Earlier entries
              </button>
            )}
          </details>
        </>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
