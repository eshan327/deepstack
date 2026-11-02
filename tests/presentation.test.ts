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
import { tableCue, playTableSound, unlockTableAudio } from "../apps/web/lib/table-sounds.ts";
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
  assert.equal(state.index, 1);
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
  assert.equal(state.index, 0);
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
  assert.equal(state.index, 1);
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


test("table audio chooses quiet event cues and defaults on while preserving an explicit mute", () => {
  assert.equal(restorePreferences({}).sounds, true);
  assert.equal(restorePreferences({ sounds: true }).sounds, true);
  assert.equal(restorePreferences({ sounds: false }).sounds, false);
  assert.equal(restorePreferences({ sounds: "true" }).sounds, true);
  const turn = { ...event(1, "board"), view: { actor: 0, complete: false } } as PublicEvent;
  assert.equal(tableCue(turn, false), "card");
  assert.equal(tableCue(turn, true), "turn");
  assert.equal(tableCue(event(2, "action", "call"), false), "chips");
  assert.equal(tableCue(event(3, "action", "check"), false), "check");
  assert.equal(tableCue(event(4), false), null);
  const award = { ...event(5, "award"), view: { seats: [{ winnings: 200 }] } } as PublicEvent;
  assert.equal(tableCue(award, false), "win");
  assert.equal(tableCue({ ...award, view: { seats: [{ winnings: 0 }] } } as PublicEvent, false), null);
  // Unsupported audio and cues before a user gesture must be harmless.
  assert.doesNotThrow(() => unlockTableAudio());
  assert.doesNotThrow(() => playTableSound("card"));
});

test("a new hand starts on its first event, without resurrecting the restored hand", () => {
  const old = result([], 1);
  old.snapshot.board = ["As", "Kh", "Qd", "Jc", "Ts"];
  old.snapshot.seats = [{ cards: ["Ac", "Ad"], winnings: 600 }] as CommandResult["snapshot"]["seats"];
  const restored = presentationReducer(initialPresentation, { type: "load", result: old, animate: false });
  const first = { ...event(10), view: { hand_number: 2, board: [], seats: [{ cards: [], winnings: 0 }] } } as PublicEvent;
  const next = presentationReducer(restored, { type: "load", result: result([first, { ...first, id: 11 }], 2), animate: true });
  assert.equal(next.index, 0);
  assert.deepEqual(next.view, first.view);
});

test("fresh command batches start immediately and retries leave the current view alone", () => {
  const loaded = presentationReducer(initialPresentation, { type: "load", result: result([event(1)]), animate: false });
  const batch = result([event(2), event(3)]);
  const playing = presentationReducer(loaded, { type: "load", result: batch, animate: true });
  assert.equal(playing.index, 1);
  assert.equal(playing.view, batch.events[0].view);
  const duplicate = presentationReducer(playing, { type: "load", result: batch, animate: true });
  assert.equal(duplicate.index, playing.index);
  assert.equal(duplicate.view, playing.view);
});

test("collection animates only the prior wagers; scrubbing shows the actual event snapshot", () => {
  const before = { ...event(1), view: { hand_number: 1, street: "Preflop", seats: [{ bet: 200 }], actor: 0 } } as PublicEvent;
  const collect = { ...event(2, "collect"), view: { hand_number: 1, street: "Flop", seats: [{ bet: 0 }], actor: null } } as PublicEvent;
  const batch = result([before, collect, event(3, "board")]);
  let state = presentationReducer(initialPresentation, { type: "load", result: batch, animate: true });
  state = presentationReducer(state, { type: "step" });
  assert.equal(state.view?.street, "Flop");
  assert.equal(state.view?.actor, null);
  assert.equal(state.view?.seats[0].bet, 200);
  state = presentationReducer(state, { type: "seek", index: 1 });
  assert.equal(state.view, collect.view);
  assert.ok(eventDuration(collect, "brisk") >= 450);
});

test("an empty new-hand response cannot strand the cursor beyond later events", () => {
  let state = presentationReducer(initialPresentation, { type: "load", result: result([event(1), event(2)]), animate: false });
  state = presentationReducer(state, { type: "load", result: result([], 2), animate: true });
  assert.equal(state.index, -1);
  state = presentationReducer(state, { type: "load", result: result([event(3)], 2), animate: true });
  assert.equal(state.index, 0);
  state = presentationReducer(state, { type: "seek", index: -100 });
  assert.equal(state.index, 0);
});
