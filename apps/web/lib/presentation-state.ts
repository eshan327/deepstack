import type { CommandResult, PublicEvent, Replay, TableView } from "./api";

export type PresentationState = {
  key: string;
  events: PublicEvent[];
  index: number;
  view: TableView | null;
  finalView: TableView | null;
  paused: boolean;
};
export const initialPresentation: PresentationState = {
  key: "",
  events: [],
  index: -1,
  view: null,
  finalView: null,
  paused: false,
};
type Update =
  | { type: "load"; result: CommandResult; animate: boolean }
  | { type: "replay"; replay: Replay }
  | { type: "step" }
  | { type: "seek"; index: number }
  | { type: "pause"; paused: boolean };

export function presentationReducer(
  state: PresentationState,
  update: Update,
): PresentationState {
  if (update.type === "pause") return { ...state, paused: update.paused };
  if (update.type === "step")
    return {
      ...state,
      index: Math.min(state.events.length - 1, state.index + 1),
    };
  if (update.type === "seek")
    return {
      ...state,
      paused: true,
      index: Math.max(0, Math.min(state.events.length - 1, update.index)),
    };
  if (update.type === "replay") {
    const { replay } = update;
    return {
      key: replay.hand.id,
      events: replay.events,
      index: Math.max(
        0,
        replay.events.findIndex((e) => e.id === replay.decisions[0]?.event_id),
      ),
      view: replay.events[0]?.view || null,
      finalView: replay.events.at(-1)?.view || null,
      paused: true,
    };
  }
  const { result, animate } = update;
  const key = `${result.snapshot.id}:${result.snapshot.hand_number}`;
  const newHand = state.key !== key;
  const existing = newHand ? [] : state.events;
  const ids = new Set(existing.map((e) => e.id));
  const events = [...existing, ...result.events.filter((e) => !ids.has(e.id))];
  return {
    key,
    events,
    index: animate ? (newHand ? -1 : state.index) : events.length - 1,
    finalView: result.snapshot,
    view: animate ? state.view : result.snapshot,
    paused: newHand ? false : state.paused,
  };
}
