"use client";
import { useCallback, useEffect, useReducer, useState } from "react";
import type { CommandResult, Preferences, Replay } from "./api";
import { eventDuration } from "./presentation";
import { initialPresentation, presentationReducer } from "./presentation-state";

export default function usePresentation(
  preferences: Preferences,
  suspended: boolean,
) {
  const [state, dispatch] = useReducer(
    presentationReducer,
    initialPresentation,
  );
  const [visible, setVisible] = useState(true);
  const { events, index, paused, finalView } = state;
  const pending = index < events.length - 1;
  const current = events[index];
  const load = useCallback(
    (result: CommandResult, animate: boolean) =>
      dispatch({ type: "load", result, animate }),
    [],
  );
  const loadReplay = useCallback(
    (replay: Replay) => dispatch({ type: "replay", replay }),
    [],
  );
  const step = useCallback(() => dispatch({ type: "step" }), []);
  const seek = useCallback(
    (index: number) => dispatch({ type: "seek", index }),
    [],
  );
  const setPaused = useCallback(
    (paused: boolean) => dispatch({ type: "pause", paused }),
    [],
  );

  useEffect(() => {
    const update = () => setVisible(document.visibilityState === "visible");
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  useEffect(() => {
    if (
      !pending ||
      paused ||
      !visible ||
      suspended ||
      preferences.pace === "manual"
    )
      return;
    const timer = setTimeout(
      step,
      current ? eventDuration(current, preferences.pace) : 80,
    );
    return () => clearTimeout(timer);
  }, [pending, paused, visible, suspended, preferences.pace, current, step]);

  const displayed =
    current?.kind === "collect"
      ? events[index - 1]?.view || current.view
      : current?.view || state.view;
  return {
    view: !pending ? finalView || displayed : displayed,
    current,
    events: events.slice(0, index + 1),
    allEvents: events,
    pending,
    paused,
    index,
    setPaused,
    step,
    load,
    loadReplay,
    seek,
  };
}
