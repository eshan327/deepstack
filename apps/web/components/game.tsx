"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  money,
  setAccountToken,
  type Command,
  type CommandResult,
  type Preferences,
  type Profile,
  type SessionList,
  type Snapshot,
  type TableConfig,
} from "@/lib/api";
import { authClient } from "@/lib/auth-client";
import { defaultPreferences, restorePreferences } from "@/lib/presentation";
import usePresentation from "@/lib/use-presentation";
import { unlockTableAudio } from "@/lib/table-sounds";
import ActionDock from "./action-dock";
import ActionLog from "./action-log";
import Drawers, { type Panel } from "./drawers";
import { Icon } from "./icons";
import PokerTable from "./table";
import Review from "./review";

type Pending = { path: string; body: unknown; animate: boolean };

export default function Game() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [panel, setPanel] = useState<Panel>(null);
  const [selectedSeat, setSelectedSeat] = useState(0);
  const [review, setReview] = useState(false);
  const locked = useRef(false);
  const pending = useRef<Pending | null>(null);
  const snapshotRef = useRef<Snapshot | null>(null);
  const profileWrites = useRef<Promise<unknown>>(Promise.resolve());
  const profileRevision = useRef(0);
  const presentation = usePresentation(preferences, review || !!panel);
  const { load } = presentation;

  const apply = useCallback(
    (result: CommandResult, animate = false) => {
      snapshotRef.current = result.snapshot;
      setSnapshot(result.snapshot);
      load(result, animate);
      try {
        localStorage.setItem("deepstack.session", result.snapshot.id);
      } catch {
        /* Optional storage. */
      }
    },
    [load],
  );

  const initialize = useCallback(async () => {
    setError("");
    try {
      const config = await fetch("/api/auth/config", {
        cache: "no-store",
      }).then((r) => r.json());
      let signedIn = false;
      if (config.configured) {
        const session = await authClient.getSession();
        if (session.error)
          throw new Error("Sign-in could not be restored. Retry shortly.");
        signedIn = !!session.data?.user;
      }
      if (signedIn) {
        let token = "",
          expires = 0;
        setAccountToken(async () => {
          if (Date.now() >= expires) {
            // Neon 0.7 otherwise reuses its session-response cache for the token endpoint.
            const result = await authClient.token({
              fetchOptions: { headers: { "X-Force-Fetch": "true" } },
            });
            if (result.error)
              throw new Error(
                result.error.message || "Sign in again to continue.",
              );
            if (!result.data?.token)
              throw new Error("Sign in again to continue.");
            token = result.data.token;
            expires = Date.now() + 5 * 60_000;
          }
          return token;
        });
        await api("/me/claim", {});
      } else {
        setAccountToken(null);
        await api("/guest", {});
      }
      const [me, sessions] = await Promise.all([
        api<Profile>("/me"),
        api<SessionList>("/sessions?active=true"),
      ]);
      setProfile(me);
      let prefs = me.preferences;
      try {
        const saved =
          localStorage.getItem("deepstack.preferences.v2") ||
          localStorage.getItem("deepstack.preferences.v1");
        if (!me.authenticated && saved)
          prefs = restorePreferences(JSON.parse(saved));
      } catch {
        /* Server defaults remain available. */
      }
      setPreferences(prefs);
      let selected = "";
      try {
        selected = localStorage.getItem("deepstack.session") || "";
      } catch {
        /* Optional storage. */
      }
      const active =
        sessions.sessions.find(
          (s) => s.id === selected && s.status === "active",
        ) || sessions.sessions.find((s) => s.status === "active");
      if (active) apply(await api<CommandResult>(`/sessions/${active.id}`));
      else {
        setSnapshot(null);
        snapshotRef.current = null;
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [apply]);

  useEffect(() => {
    // Restore browser cookies and preferences after hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void initialize();
  }, [initialize]);

  const commandError = useCallback(
    async (failure: ApiError) => {
      if (failure.status && failure.status < 500) pending.current = null;
      if (failure.status === 409 && snapshotRef.current) {
        const latest = await api<CommandResult>(
          `/sessions/${snapshotRef.current.id}`,
        ).catch(() => null);
        if (latest) apply(latest);
      }
      setError(failure.message);
    },
    [apply],
  );

  const command = useCallback(
    async (fields: Omit<Command, "command_id" | "expected_version">) => {
      const current = snapshotRef.current;
      if (!current || locked.current || pending.current || presentation.pending)
        return false;
      locked.current = true;
      setBusy(true);
      setError("");
      const request = {
        path: `/sessions/${current.id}/commands`,
        body: {
          ...fields,
          command_id: crypto.randomUUID(),
          expected_version: current.version,
        },
        animate: ["act", "advance", "next_hand"].includes(fields.kind),
      };
      pending.current = request;
      try {
        const result = await api<CommandResult>(request.path, request.body);
        pending.current = null;
        apply(result, request.animate);
        return true;
      } catch (e) {
        await commandError(e as ApiError);
        return false;
      } finally {
        locked.current = false;
        setBusy(false);
      }
    },
    [apply, commandError, presentation.pending],
  );

  useEffect(() => {
    if (
      snapshot?.needs_advance &&
      !busy &&
      !presentation.pending &&
      !presentation.paused &&
      preferences.pace !== "manual" &&
      !error &&
      !panel &&
      !review
    )
      void command({ kind: "advance" });
  }, [
    snapshot,
    busy,
    presentation.pending,
    presentation.paused,
    preferences.pace,
    error,
    panel,
    review,
    command,
  ]);

  async function retry() {
    if (locked.current) return;
    if (!pending.current) {
      setLoading(true);
      await initialize();
      return;
    }
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api<CommandResult>(
        pending.current.path,
        pending.current.body,
      );
      const animate = pending.current.animate;
      pending.current = null;
      apply(result, animate);
    } catch (e) {
      await commandError(e as ApiError);
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  async function saveProfile(next: Profile) {
    const revision = ++profileRevision.current;
    const write = profileWrites.current
      .catch(() => {})
      .then(() =>
        api<Profile>("/me", {
          name: next.name,
          preferences: next.preferences,
          table_defaults: next.table_defaults,
        }),
      );
    profileWrites.current = write;
    const saved = await write;
    if (revision !== profileRevision.current) return;
    setProfile(saved);
    setPreferences(saved.preferences);
    try {
      localStorage.setItem(
        "deepstack.preferences.v2",
        JSON.stringify(saved.preferences),
      );
    } catch {
      /* Optional storage. */
    }
  }

  function updatePreferences(next: Preferences) {
    if (next.sounds) unlockTableAudio();
    setPreferences(next);
    try {
      localStorage.setItem("deepstack.preferences.v2", JSON.stringify(next));
    } catch {
      /* Optional storage. */
    }
    if (profile)
      void saveProfile({ ...profile, preferences: next }).catch((e) =>
        setError(e.message),
      );
  }

  async function create(config: TableConfig) {
    if (locked.current || pending.current || presentation.pending) return;
    const amounts = [
      config.small_blind,
      config.big_blind,
      config.starting_stack,
      ...(config.seat_stacks || []),
    ];
    if (amounts.some((n) => !Number.isSafeInteger(n) || n <= 0 || n > 1e12))
      throw new Error(
        "Use positive chip amounts with at most two decimal places.",
      );
    if (config.small_blind > config.big_blind)
      throw new Error("The small blind cannot exceed the big blind.");
    if (config.seat_stacks && config.seat_stacks.length !== config.players)
      throw new Error("Supply one starting stack per seat.");
    const previous = snapshotRef.current;
    if (previous?.status === "active" && !(await command({ kind: "end" })))
      return;
    locked.current = true;
    setBusy(true);
    setError("");
    pending.current = {
      path: "/sessions",
      body: {
        command_id: crypto.randomUUID(),
        config,
        previous_session_id: previous?.id || null,
      },
      animate: false,
    };
    try {
      const result = await api<CommandResult>(
        pending.current.path,
        pending.current.body,
      );
      pending.current = null;
      apply(result);
      setPanel(null);
      setReview(false);
      if (profile)
        await saveProfile({
          ...profile,
          table_defaults: {
            ...config,
            seat_stacks: config.seat_stacks ?? null,
          },
        });
    } catch (e) {
      const err = e as ApiError;
      if (err.status && err.status < 500) pending.current = null;
      setError(err.message);
      throw e;
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  async function loadSession(id: string) {
    if (locked.current || pending.current) return;
    setBusy(true);
    try {
      apply(await api<CommandResult>(`/sessions/${id}`));
      setReview(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const view = presentation.view;
  const bb = preferences.bb ? snapshot?.config.big_blind : undefined;
  const blocked = busy || presentation.pending || !!error;
  const shownSnapshot =
    snapshot && view
      ? { ...snapshot, ...view, legal: snapshot.legal }
      : snapshot;
  function step() {
    if (presentation.pending) presentation.step();
    else if (snapshot?.needs_advance) void command({ kind: "advance" });
  }

  return (
    <main
      className={`poker-app ${preferences.reducedMotion ? "reduced-motion" : ""}`}
    >
      <header className="app-header">
        <button className="wordmark" onClick={() => setReview(false)}>
          DEEPSTACK
        </button>
        <nav aria-label="Main navigation">
          <button
            className={!review ? "active" : ""}
            onClick={() => setReview(false)}
          >
            Play
          </button>
          <button
            className={review ? "active" : ""}
            onClick={() => setReview(true)}
          >
            Review
          </button>
        </nav>
        <div className="header-tools">
          {!review && (
            <button
              aria-label="Action log"
              aria-pressed={preferences.actionLog}
              onClick={() => {
                if (window.matchMedia("(max-width: 1200px)").matches)
                  setPanel("log");
                else
                  updatePreferences({
                    ...preferences,
                    actionLog: !preferences.actionLog,
                  });
              }}
            >
              <Icon name="log" />
              <span>Action log</span>
            </button>
          )}
          <button
            className="icon-button"
            aria-label="Toggle table sounds"
            aria-pressed={preferences.sounds}
            title={
              preferences.sounds ? "Mute table sounds" : "Enable table sounds"
            }
            onClick={() =>
              updatePreferences({ ...preferences, sounds: !preferences.sounds })
            }
          >
            <Icon name={preferences.sounds ? "sound" : "muted"} />
          </button>
          <button
            aria-label="Table settings"
            className="icon-button"
            onClick={() => setPanel("settings")}
          >
            <Icon name="settings" />
          </button>
          <button
            className="profile-button"
            aria-label="Your account"
            onClick={() => setPanel("account")}
          >
            <span className="profile-monogram">
              {profile?.name?.[0] || "Y"}
            </span>
            <span>{profile?.name || "You"}</span>
          </button>
        </div>
      </header>
      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button disabled={busy} onClick={() => void retry()}>
            Retry
          </button>
        </div>
      )}
      <div
        hidden={review}
        className={`play-workspace ${preferences.actionLog ? "with-log" : ""}`}
        tabIndex={0}
        aria-label="Play workspace"
      >
        <div className="table-column">
          <div className="table-toolbar">
            <div className="table-meta">
              <span>No-limit Hold’em</span>
              <strong>
                {money(snapshot?.config.small_blind || 100)} /{" "}
                {money(snapshot?.config.big_blind || 200)}
              </strong>
              <span>
                {snapshot?.config.players ||
                  profile?.table_defaults.players ||
                  6}{" "}
                players
              </span>
              <span>
                {snapshot?.hand_number
                  ? `Hand ${String(snapshot.hand_number).padStart(3, "0")}`
                  : "Your table"}
              </span>
              <button
                className="unit-toggle"
                aria-label="Toggle dollar and big blind display"
                aria-pressed={preferences.bb}
                onClick={() =>
                  updatePreferences({ ...preferences, bb: !preferences.bb })
                }
              >
                $ / BB
              </button>
            </div>
            <div className="playback-tools">
              <button
                onClick={() => presentation.setPaused(!presentation.paused)}
                aria-label={
                  presentation.paused ? "Resume playback" : "Pause playback"
                }
              >
                <Icon name={presentation.paused ? "play" : "pause"} size={16} />
                <span>{presentation.paused ? "Resume" : "Pause"}</span>
              </button>
              <button
                className="icon-button step-button"
                aria-label="Next action"
                disabled={
                  (!presentation.pending && !snapshot?.needs_advance) || busy
                }
                onClick={step}
              >
                <Icon name="skip" size={16} />
              </button>
              <select
                aria-label="Presentation speed"
                value={preferences.pace}
                onChange={(e) =>
                  updatePreferences({
                    ...preferences,
                    pace: e.target.value as Preferences["pace"],
                  })
                }
              >
                <option value="deliberate">Deliberate</option>
                <option value="brisk">Brisk</option>
                <option value="manual">Manual</option>
              </select>
            </div>
          </div>
          {loading ? (
            <PokerTable
              view={null}
              fourColor={preferences.fourColor}
              onSelect={() => {}}
            />
          ) : snapshot && view ? (
            <>
              <PokerTable
                key={`${snapshot.id}:${view.hand_number}`}
                view={view}
                bb={bb}
                fourColor={preferences.fourColor}
                latestSeat={presentation.current?.seat}
                eventKind={presentation.current?.kind}
                dealtSeats={presentation.dealtSeats}
                onSelect={(seat) => {
                  setSelectedSeat(seat);
                  setPanel("player");
                }}
              />
              <ActionDock
                key={`${snapshot.id}:${snapshot.hand_number}:${snapshot.street}:${snapshot.pot}:${snapshot.legal.min_raise_to}:${snapshot.seats[0].stack}`}
                snapshot={shownSnapshot}
                busy={blocked}
                bb={bb}
                onAct={(action) => void command({ kind: "act", action })}
                onNext={() => void command({ kind: "next_hand" })}
                onTopUp={() => {
                  setSelectedSeat(0);
                  setPanel("player");
                }}
                onSitIn={() =>
                  void command({
                    kind: "set_seat",
                    seat: 0,
                    sitting_out: false,
                  })
                }
                onStart={() => setPanel("settings")}
              />
            </>
          ) : (
            <section className="welcome-table">
              <div className="welcome-felt" />
              <div className="welcome-content">
                <span className="welcome-mark" aria-hidden="true">
                  ♠
                </span>
                <h1>No table open</h1>
                <button
                  className="primary"
                  disabled={busy || !!error}
                  onClick={() => setPanel("settings")}
                >
                  Set up your table <Icon name="arrow" />
                </button>
              </div>
            </section>
          )}
        </div>
        {preferences.actionLog && (
          <aside className="live-action-rail">
            <div className="rail-heading">
              <h2>This hand</h2>
              <button
                className="icon-button"
                aria-label="Close action log"
                onClick={() =>
                  updatePreferences({ ...preferences, actionLog: false })
                }
              >
                <Icon name="close" />
              </button>
            </div>
            <ActionLog events={presentation.events} bb={bb} />
            <button className="text-button" onClick={() => setReview(true)}>
              Review your hands <Icon name="arrow" size={16} />
            </button>
          </aside>
        )}
      </div>
      {review && (
        <Review
          preferences={preferences}
          activeSession={snapshot?.id}
          onResume={() => setReview(false)}
          onLoadSession={loadSession}
        />
      )}
      <Drawers
        panel={panel}
        onClose={() => setPanel(null)}
        snapshot={snapshot}
        selectedSeat={selectedSeat}
        preferences={preferences}
        onPreferences={updatePreferences}
        onCommand={command}
        onCreate={create}
        profile={profile}
        onProfile={saveProfile}
        events={presentation.events}
        busy={blocked}
        onSignedOut={async () => {
          setAccountToken(null);
          await api("/guest/reset", {});
          window.location.reload();
        }}
      />
      <span className="sr-only" role="status">
        {!blocked && snapshot?.actor === 0 ? "Your turn." : ""}
      </span>
    </main>
  );
}
