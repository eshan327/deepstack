import type { Preferences, PublicEvent } from "./api";

export const defaultPreferences: Preferences = {
  bb: false,
  pace: "deliberate",
  fourColor: false,
  reducedMotion: false,
  actionLog: false,
};

export function restorePreferences(
  saved: Record<string, unknown>,
): Preferences {
  return {
    bb: saved.bb === true,
    fourColor: saved.fourColor === true,
    reducedMotion: saved.reducedMotion === true,
    actionLog: saved.actionLog === true,
    pace:
      saved.pace === "manual" || saved.pace === "brisk"
        ? saved.pace
        : saved.fast === true
          ? "brisk"
          : "deliberate",
  };
}

export function eventDuration(event: PublicEvent, pace: Preferences["pace"]) {
  let duration = 1600;
  if (event.kind === "deal") duration = 140;
  else if (event.kind === "collect") duration = 450;
  else if (event.kind === "board") duration = 1500;
  else if (event.kind === "show") duration = 2000;
  else if (event.kind === "award") duration = 2400;
  else if (event.kind === "complete") duration = 800;
  else if (
    event.action === "check" ||
    event.action === "fold" ||
    /:\s*(Fold|Check)/.test(event.text)
  )
    duration = 1200;
  return pace === "brisk"
    ? Math.max(100, Math.round(duration * 0.35))
    : duration;
}
