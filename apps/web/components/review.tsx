"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  money,
  requestHeaders,
  type AnalysisResult,
  type HandSummary,
  type Preferences,
  type Replay,
  type ReviewHands,
  type SessionList,
} from "@/lib/api";
import usePresentation from "@/lib/use-presentation";
import ActionLog from "./action-log";
import { Icon } from "./icons";
import PokerTable, { Card } from "./table";

export default function Review({
  preferences,
  activeSession,
  onResume,
  onLoadSession,
}: {
  preferences: Preferences;
  activeSession?: string;
  onResume: () => void;
  onLoadSession: (id: string) => Promise<void>;
}) {
  const [sessions, setSessions] = useState<SessionList["sessions"]>([]);
  const [session, setSession] = useState("");
  const [days, setDays] = useState("");
  const [stakes, setStakes] = useState("");
  const [saved, setSaved] = useState(false);
  const [hands, setHands] = useState<HandSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [decision, setDecision] = useState(0);
  const [ranges, setRanges] = useState<Record<number, string>>({});
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [note, setNote] = useState("");
  const [noteSaved, setNoteSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [gridSeat, setGridSeat] = useState<number | null>(null);
  const selection = useRef(0);
  const analysisRun = useRef(0);
  const queryRun = useRef(0);
  const playback = usePresentation(
    {
      ...preferences,
      pace: preferences.pace === "manual" ? "deliberate" : preferences.pace,
    },
    false,
  );
  const { loadReplay } = playback;

  useEffect(() => {
    void api<SessionList>("/sessions")
      .then((data) => setSessions(data.sessions))
      .catch((e) => setError(e.message));
  }, []);

  const openHand = useCallback(
    async (hand: HandSummary) => {
      const run = ++selection.current;
      analysisRun.current++;
      setReplay(null);
      setAnalysis(null);
      setRanges({});
      setDecision(0);
      setError("");
      setAnalyzing(false);
      try {
        const data = await api<Replay>(`/hands/${hand.id}`);
        if (selection.current !== run) return;
        setReplay(data);
        loadReplay(data);
        setNote(data.hand.note);
        setNoteSaved(false);
      } catch (e) {
        if (selection.current === run) setError((e as Error).message);
      }
    },
    [loadReplay],
  );

  useEffect(() => {
    const run = ++queryRun.current;
    let cancelled = false;
    // The external query changes with the user's filters.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    if (session) params.set("session_id", session);
    if (days) params.set("days", days);
    if (stakes) params.set("big_blind", stakes);
    if (saved) params.set("saved", "true");
    api<ReviewHands>(`/hands?${params}`)
      .then((data) => {
        if (cancelled || run !== queryRun.current) return;
        setHands(data.hands);
        setCursor(data.next_cursor);
        setLoading(false);
        if (data.hands[0]) void openHand(data.hands[0]);
        else {
          selection.current++;
          setReplay(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [session, days, stakes, saved, openHand]);

  async function more() {
    if (!cursor || loading) return;
    const run = queryRun.current;
    setLoading(true);
    const params = new URLSearchParams({ before: cursor });
    if (session) params.set("session_id", session);
    if (days) params.set("days", days);
    if (stakes) params.set("big_blind", stakes);
    if (saved) params.set("saved", "true");
    try {
      const data = await api<ReviewHands>(`/hands?${params}`);
      if (run !== queryRun.current) return;
      setHands((old) => [...old, ...data.hands]);
      setCursor(data.next_cursor);
    } catch (e) {
      if (run === queryRun.current) setError((e as Error).message);
    } finally {
      if (run === queryRun.current) setLoading(false);
    }
  }

  async function annotation(bookmarked: boolean, text: string) {
    if (!replay || saving) return;
    const run = selection.current;
    setSaving(true);
    setError("");
    try {
      const hand = await api<HandSummary>(
        `/hands/${replay.hand.id}/annotation`,
        { bookmarked, note: text },
      );
      setHands((old) => old.map((h) => (h.id === hand.id ? hand : h)));
      setReplay((old) =>
        old && old.hand.id === hand.id ? { ...old, hand } : old,
      );
      if (run === selection.current) setNoteSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function seek(index: number) {
    playback.seek(index);
    const event = replay?.events[index];
    if (!event || !replay) return;
    const contextIndex = replay.decisions.findLastIndex(
      (d) => d.event_id <= event.id,
    );
    if (contextIndex >= 0 && contextIndex !== decision) {
      setDecision(contextIndex);
      setAnalysis(null);
      setRanges({});
      analysisRun.current++;
    }
  }

  function chooseDecision(index: number) {
    setDecision(index);
    setRanges({});
    setAnalysis(null);
    analysisRun.current++;
    const event = replay?.decisions[index]?.event_id;
    if (event != null)
      playback.seek(
        Math.max(
          0,
          replay!.events.findIndex((e) => e.id === event),
        ),
      );
  }

  async function calculate() {
    if (!replay) return;
    const run = ++analysisRun.current;
    setAnalyzing(true);
    setError("");
    try {
      const result = await api<AnalysisResult>(
        `/hands/${replay.hand.id}/analysis`,
        { decision, ranges },
      );
      if (analysisRun.current === run) setAnalysis(result);
    } catch (e) {
      if (analysisRun.current === run) setError((e as Error).message);
    } finally {
      if (analysisRun.current === run) setAnalyzing(false);
    }
  }

  async function exportHand(format: "text" | "json") {
    if (!replay) return;
    try {
      const response = await fetch(
        `/api/v1/hands/${replay.hand.id}/export?format=${format}`,
        {
          credentials: "same-origin",
          cache: "no-store",
          headers: await requestHeaders(),
        },
      );
      if (!response.ok)
        throw new Error("The hand could not be exported. Try again.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `deepstack-${replay.hand.number}.${format === "text" ? "txt" : "json"}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const context = replay?.decisions[decision];
  const opponents =
    context?.view.seats.filter((s) => s.seat > 0 && s.in_hand && !s.folded) ||
    [];
  const bb = preferences.bb ? replay?.hand.big_blind : undefined;
  const selectedSession = sessions.find((s) => s.id === session);
  return (
    <section className="review-workspace" aria-label="Review workspace">
      <div className="review-heading">
        <h1>Review</h1>
        <button className="secondary" onClick={onResume}>
          Resume table
        </button>
      </div>
      <div className="review-filters">
        <select
          aria-label="Filter session"
          value={session}
          onChange={(e) => setSession(e.target.value)}
        >
          <option value="">All sessions</option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {new Date(s.created_at).toLocaleDateString()} ·{" "}
              {s.config
                ? `${money(s.config.small_blind)} / ${money(s.config.big_blind)}`
                : "Table"}{" "}
              · {s.hands} hands
            </option>
          ))}
        </select>
        <select
          aria-label="Filter date"
          value={days}
          onChange={(e) => setDays(e.target.value)}
        >
          <option value="">All dates</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
          <option value="90">Last 90 days</option>
        </select>
        <select
          aria-label="Filter stakes"
          value={stakes}
          onChange={(e) => setStakes(e.target.value)}
        >
          <option value="">All stakes</option>
          {[
            ...new Set(
              sessions
                .map((s) => s.config?.big_blind)
                .filter((n): n is number => !!n),
            ),
          ]
            .sort((a, b) => a - b)
            .map((n) => (
              <option key={n} value={n}>
                {money(n)} big blind
              </option>
            ))}
        </select>
        <button
          className="secondary saved-filter"
          aria-pressed={saved}
          onClick={() => setSaved(!saved)}
        >
          <Icon name="bookmark" size={16} />
          Saved hands
        </button>
        <details className="export-menu">
          <summary>Export</summary>
          <div className="export-options">
            <button disabled={!replay} onClick={() => void exportHand("text")}>
              Text history
            </button>
            <button disabled={!replay} onClick={() => void exportHand("json")}>
              JSON history
            </button>
          </div>
        </details>
      </div>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      <div className="review-columns">
        <aside className="hand-browser" aria-label="Saved hands">
          {selectedSession && (
            <div className="session-overview">
              <strong>{selectedSession.hands} hands</strong>
              <span
                className={
                  selectedSession.profit >= 0 ? "positive" : "negative"
                }
              >
                {money(selectedSession.profit)}
              </span>
              {selectedSession.status === "active" &&
                selectedSession.id !== activeSession && (
                  <button
                    className="text-button"
                    onClick={() => void onLoadSession(selectedSession.id)}
                  >
                    Resume this table
                  </button>
                )}
            </div>
          )}
          <div className="hand-list-heading">
            <span>Hand</span>
            <span>Cards</span>
            <span>Pos</span>
            <span>Result</span>
          </div>
          {hands.map((hand) => (
            <button
              key={hand.id}
              className={`hand-row ${replay?.hand.id === hand.id ? "selected" : ""}`}
              onClick={() => void openHand(hand)}
            >
              <span>{hand.number}</span>
              <span className="hand-cards">
                <span className="mini-hand">
                  {hand.hero_cards.map((c) => (
                    <Card card={c} key={c} small />
                  ))}
                </span>
                <small className="hand-pot">
                  Pot{" "}
                  {money(hand.pot, preferences.bb ? hand.big_blind : undefined)}
                </small>
              </span>
              <span>{hand.position || "—"}</span>
              <span className={hand.profit >= 0 ? "positive" : "negative"}>
                {hand.profit > 0 ? "+" : ""}
                {money(
                  hand.profit,
                  preferences.bb ? hand.big_blind : undefined,
                )}
              </span>
              <span className={hand.bookmarked ? "bookmarked" : "muted"}>
                <Icon name="bookmark" size={14} />
              </span>
            </button>
          ))}
          {loading && <p className="empty-copy">Loading hands…</p>}
          {!loading && !hands.length && (
            <p className="empty-copy">
              {saved ? "No saved hands." : "No completed hands."}
            </p>
          )}
          {cursor && (
            <button
              className="secondary full"
              disabled={loading}
              onClick={() => void more()}
            >
              Earlier hands
            </button>
          )}
        </aside>
        <div className="hand-replay">
          {replay ? (
            <>
              <div className="replay-heading">
                <div>
                  <h2>Hand {String(replay.hand.number).padStart(3, "0")}</h2>
                  <p>
                    {playback.view?.street} · {money(replay.hand.big_blind)} big
                    blind · {replay.hand.players} players
                  </p>
                </div>
                <button
                  className={`icon-button ${replay.hand.bookmarked ? "bookmarked" : ""}`}
                  aria-label={
                    replay.hand.bookmarked ? "Unsave hand" : "Save hand"
                  }
                  aria-pressed={replay.hand.bookmarked}
                  disabled={saving}
                  onClick={() => void annotation(!replay.hand.bookmarked, note)}
                >
                  <Icon name="bookmark" />
                </button>
              </div>
              <PokerTable
                view={playback.view}
                fourColor={preferences.fourColor}
                bb={bb}
                replay
                latestSeat={playback.current?.seat}
                eventKind={playback.current?.kind}
                onSelect={() => {}}
              />
              <div className="street-tabs">
                {["Preflop", "Flop", "Turn", "River"].map((street) => {
                  const index = replay.events.findIndex(
                    (e) => e.view.street === street,
                  );
                  return (
                    <button
                      key={street}
                      disabled={index < 0}
                      aria-pressed={playback.view?.street === street}
                      onClick={() => seek(index)}
                    >
                      {street}
                    </button>
                  );
                })}
              </div>
              <div className="replay-stepper">
                <button
                  className="icon-button"
                  aria-label="Previous action"
                  disabled={playback.index <= 0}
                  onClick={() => seek(playback.index - 1)}
                >
                  <Icon name="chevron" />
                </button>
                <input
                  aria-label="Replay action"
                  type="range"
                  min={0}
                  max={Math.max(0, replay.events.length - 1)}
                  value={playback.index}
                  onChange={(e) => seek(Number(e.target.value))}
                />
                <button
                  className="icon-button"
                  aria-label={
                    !playback.pending
                      ? "Restart replay"
                      : playback.paused
                        ? "Play replay"
                        : "Pause replay"
                  }
                  onClick={() => {
                    if (!playback.pending) {
                      playback.seek(0);
                      playback.setPaused(false);
                    } else playback.setPaused(!playback.paused);
                  }}
                >
                  <Icon
                    name={
                      playback.paused || !playback.pending ? "play" : "pause"
                    }
                  />
                </button>
                <button
                  className="icon-button"
                  aria-label="Next replay action"
                  disabled={playback.index >= replay.events.length - 1}
                  onClick={() => seek(playback.index + 1)}
                >
                  <Icon name="skip" />
                </button>
              </div>
              <ActionLog
                events={replay.events}
                bb={bb}
                selected={playback.index}
                onSelect={seek}
              />
            </>
          ) : (
            <div className="review-placeholder">
              <Icon name="history" size={36} />
              <h2>Select a hand</h2>
            </div>
          )}
        </div>
        <aside className="decision-inspector" aria-label="Decision review">
          <div className="inspector-heading">
            <h2>Decision review</h2>
          </div>
          {replay && context ? (
            <>
              <label className="form-label">
                Your decision
                <select
                  aria-label="Jump to your decision"
                  value={decision}
                  onChange={(e) => chooseDecision(Number(e.target.value))}
                >
                  {replay.decisions.map((d, i) => (
                    <option key={i} value={i}>
                      {d.view.street} · {d.action.kind.replaceAll("_", " ")}
                      {d.action.amount ? ` ${money(d.action.amount)}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <dl className="decision-facts">
                <div>
                  <dt>Pot before action</dt>
                  <dd>{money(context.view.pot, bb)}</dd>
                </div>
                <div>
                  <dt>To call</dt>
                  <dd>{money(context.legal.call || 0, bb)}</dd>
                </div>
                <div>
                  <dt>Effective stack</dt>
                  <dd>{money(context.effective_stack, bb)}</dd>
                </div>
              </dl>
              {analysis && (
                <div className="equity-result">
                  <div>
                    <span>Equity</span>
                    <strong>{Math.round(analysis.equity * 100)}%</strong>
                  </div>
                  <div className="equity-bar">
                    <span style={{ width: `${analysis.equity * 100}%` }} />
                    {analysis.call_threshold != null && (
                      <i
                        style={{ left: `${analysis.call_threshold * 100}%` }}
                      />
                    )}
                  </div>
                  <p className="muted small">
                    ±{Math.ceil(analysis.uncertainty * 100)} percentage points ·{" "}
                    {analysis.samples} samples
                  </p>
                  {analysis.call_threshold != null && (
                    <p className="threshold">
                      Call price{" "}
                      <strong>
                        {Math.round(analysis.call_threshold * 100)}%
                      </strong>
                    </p>
                  )}
                  <p className="analysis-explanation">{analysis.explanation}</p>
                </div>
              )}
              <details className="review-ranges">
                <summary>
                  Opponent ranges{" "}
                  <span className="muted small">
                    {opponents.length} players
                  </span>
                </summary>
                {opponents.map((p) => (
                  <div className="range-editor" key={p.seat}>
                    <label className="form-label">
                      {p.name} <span className="muted">{p.position}</span>
                      <input
                        aria-label={`${p.name} range`}
                        maxLength={1000}
                        value={ranges[p.seat] ?? "random"}
                        onChange={(e) => {
                          setRanges({ ...ranges, [p.seat]: e.target.value });
                          setAnalysis(null);
                          analysisRun.current++;
                          setAnalyzing(false);
                        }}
                      />
                    </label>
                    <button
                      className="text-button small"
                      onClick={() =>
                        setGridSeat(gridSeat === p.seat ? null : p.seat)
                      }
                    >
                      {gridSeat === p.seat
                        ? "Close range grid"
                        : "Edit range grid"}
                      <Icon name="chevron" size={12} />
                    </button>
                    {gridSeat === p.seat && (
                      <RangeGrid
                        value={ranges[p.seat] ?? "random"}
                        onChange={(value) => {
                          setRanges({ ...ranges, [p.seat]: value });
                          setAnalysis(null);
                          analysisRun.current++;
                          setAnalyzing(false);
                        }}
                      />
                    )}
                  </div>
                ))}
                <p className="muted small">
                  random = all hands · Examples: 77+, AJs+, KQs
                </p>
              </details>
              <button
                className="secondary full"
                disabled={analyzing}
                onClick={() => void calculate()}
              >
                {analyzing
                  ? "Analyzing…"
                  : analysis
                    ? "Recalculate"
                    : "Analyze decision"}
              </button>
            </>
          ) : (
            <p className="empty-copy">
              {replay
                ? "No analysis recorded for this hand."
                : "No hand selected."}
            </p>
          )}
          {replay && (
            <form
              className="study-note"
              onSubmit={(e) => {
                e.preventDefault();
                void annotation(replay.hand.bookmarked, note);
              }}
            >
              <h3 className="section-label">Study note</h3>
              <label className="sr-only" htmlFor="study-note">
                Study note
              </label>
              <textarea
                id="study-note"
                maxLength={2000}
                value={note}
                placeholder="Add a note"
                onChange={(e) => {
                  setNote(e.target.value);
                  setNoteSaved(false);
                }}
              />
              <button className="secondary" disabled={saving}>
                {noteSaved ? "Saved" : "Save note"}
              </button>
            </form>
          )}
        </aside>
      </div>
    </section>
  );
}

function RangeGrid({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const ranks = "AKQJT98765432".split("");
  const [expanded, setExpanded] = useState<{
    value: string;
    hands: string[];
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    api<{ hands: string[] }>("/ranges/expand", { range: value })
      .then((data) => {
        if (!cancelled) {
          setExpanded({ value, hands: data.hands });
          setError("");
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [value]);
  const chosen = new Set(expanded?.value === value ? expanded.hands : []);
  return (
    <>
      {error && (
        <p className="error-text small" role="alert">
          {error}
        </p>
      )}
      <div className="range-grid" aria-label="Starting hand range grid">
        {ranks.flatMap((a, i) =>
          ranks.map((b, j) => {
            const hand =
              i === j ? `${a}${b}` : i < j ? `${a}${b}s` : `${b}${a}o`;
            const selected = chosen.has(hand);
            return (
              <button
                type="button"
                key={hand}
                disabled={expanded?.value !== value}
                aria-pressed={selected}
                onClick={() => {
                  const all = new Set(chosen);
                  if (all.has(hand)) all.delete(hand);
                  else all.add(hand);
                  onChange([...all].join(", "));
                }}
              >
                {hand}
              </button>
            );
          }),
        )}
      </div>
    </>
  );
}
