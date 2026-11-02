import type { CommandResult, PublicEvent, Replay, TableView } from "./api";

export type PresentationState = {
  key: string;
  events: PublicEvent[];
  index: number;
  view: TableView | null;
  finalView: TableView | null;
  paused: boolean;
  animate: boolean;
};
export const initialPresentation: PresentationState = {
  key: "",
  events: [],
  index: -1,
  view: null,
  finalView: null,
  paused: false,
  animate: false,
};
type Update =
  | { type: "load"; result: CommandResult; animate: boolean }
  | { type: "replay"; replay: Replay }
  | { type: "step" }
  | { type: "seek"; index: number }
  | { type: "pause"; paused: boolean };

function present(
  state: PresentationState,
  index: number,
  animate: boolean,
): PresentationState {
  const event = state.events[index];
  let view = event?.view || state.finalView;
  if (animate && event?.kind === "collect") {
    // Only the wagers linger while collecting; actor, street and cards are current.
    view = {
      ...event.view,
      seats: event.view.seats.map((seat, i) => ({
        ...seat,
        bet: state.view?.seats[i]?.bet || 0,
      })),
    };
  } else if (animate && index === state.events.length - 1) {
    view = state.finalView || view;
  }
  return { ...state, index, view, animate };
}

export function presentationReducer(
  state: PresentationState,
  update: Update,
): PresentationState {
  if (update.type === "pause") return { ...state, paused: update.paused };
  if (update.type === "step") {
    if (state.index >= state.events.length - 1) return state;
    return present(state, state.index + 1, true);
  }
  if (update.type === "seek")
    return present(
      { ...state, paused: true },
      Math.min(state.events.length - 1, Math.max(0, update.index)),
      false,
    );
  if (update.type === "replay") {
    const { replay } = update;
    const index = Math.min(replay.events.length - 1, Math.max(
      0, replay.events.findIndex((e) => e.id === replay.decisions[0]?.event_id),
    ));
    return present({
      ...initialPresentation,
      key: replay.hand.id,
      events: replay.events,
      finalView: replay.events.at(-1)?.view || null,
      paused: true,
    }, index, false);
  }
  const { result, animate } = update;
  const key = `${result.snapshot.id}:${result.snapshot.hand_number}`;
  const newHand = state.key !== key;
  const existing = newHand ? [] : state.events;
  const ids = new Set(existing.map((e) => e.id));
  const fresh = result.events.filter((event) => {
    if (ids.has(event.id)) return false;
    ids.add(event.id);
    return true;
  });
  const events = [...existing, ...fresh];
  const next = {
    ...state,
    key,
    events,
    finalView: result.snapshot,
    paused: newHand ? false : state.paused,
  };
  if (!animate || !events.length)
    return { ...next, index: events.length - 1, view: result.snapshot, animate: false };
  if (fresh.length && (newHand || state.index === existing.length - 1))
    return present(next, existing.length, true);
  return { ...next, view: state.index < events.length - 1 ? state.view : result.snapshot };
}
