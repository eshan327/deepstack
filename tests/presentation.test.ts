import assert from "node:assert/strict";
import test from "node:test";
import {
  presentationReducer,
  initialPresentation,
} from "../apps/web/lib/presentation-state.ts";
import {
  eventDuration,
  restorePreferences,
} from "../apps/web/lib/presentation.ts";
import type { CommandResult, PublicEvent } from "../apps/web/lib/api.ts";

const event = (id: number, kind = "action", action = "fold") =>
  ({
    id,
    kind,
    action,
    text: "Player: Fold",
    view: { hand_number: 1 },
  }) as PublicEvent;
function result(events: PublicEvent[], hand = 1) {
  return {
    events,
    snapshot: { id: "table", hand_number: hand },
  } as CommandResult;
}

test("notes retain the hand log and duplicated responses never repeat actions", () => {
  let state = presentationReducer(initialPresentation, {
    type: "load",
    result: result([event(1)]),
    animate: false,
  });
  state = presentationReducer(state, {
    type: "load",
    result: result([event(2), event(3)]),
    animate: true,
  });
  assert.equal(state.index, 0);
  state = presentationReducer(state, { type: "step" });
  assert.equal(state.events[state.index].id, 2);
  state = presentationReducer(state, {
    type: "load",
    result: result([event(2), event(3)]),
    animate: true,
  });
  assert.equal(state.index, 1);
  assert.deepEqual(
    state.events.map((e) => e.id),
    [1, 2, 3],
  );
  state = presentationReducer(state, { type: "step" });
  state = presentationReducer(state, {
    type: "load",
    result: result([]),
    animate: false,
  });
  assert.deepEqual(
    state.events.map((e) => e.id),
    [1, 2, 3],
  );
  state = presentationReducer(state, {
    type: "load",
    result: result([event(4)], 2),
    animate: true,
  });
  assert.equal(state.index, -1);
  assert.deepEqual(
    state.events.map((e) => e.id),
    [4],
  );
});

test("pause and stepping do not discard queued events; seek stays within the hand", () => {
  let state = presentationReducer(initialPresentation, {
    type: "load",
    result: result([event(1), event(2)]),
    animate: true,
  });
  state = presentationReducer(state, { type: "pause", paused: true });
  state = presentationReducer(state, { type: "step" });
  assert.equal(state.index, 0);
  assert.equal(state.paused, true);
  assert.equal(state.events.length, 2);
  state = presentationReducer(state, { type: "seek", index: 100 });
  assert.equal(state.index, 1);
  state = presentationReducer(state, { type: "seek", index: -20 });
  assert.equal(state.index, 0);
});

test("legacy preferences migrate without conflating reduced motion and speed", () => {
  const prefs = restorePreferences({
    fast: false,
    reducedMotion: true,
    pace: "nonsense",
    bb: true,
  });
  assert.equal(prefs.pace, "deliberate");
  assert.equal(prefs.reducedMotion, true);
  assert.equal(eventDuration(event(1), prefs.pace), 1200);
  assert.equal(restorePreferences({ fast: true }).pace, "brisk");
  assert.ok(eventDuration(event(2, "show"), "deliberate") >= 2000);
  assert.ok(
    eventDuration(event(3, "award"), "brisk") <
      eventDuration(event(3, "award"), "deliberate"),
  );
});
