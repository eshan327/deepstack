import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { defaults, money, type CommandResult, type Replay } from "../../apps/web/lib/api";
import { defaultPreferences, eventDuration } from "../../apps/web/lib/presentation";

type Fixture = { initial: CommandResult["snapshot"]; batches: CommandResult[]; replays: Replay[] };
function fixture(players: number, scenario = "checkdown"): Fixture {
  return JSON.parse(execFileSync("uv", ["run", "python", "-m", "tests.presentation_fixture", String(players), scenario], {
    cwd: path.join(process.cwd(), "apps/api"), encoding: "utf8", maxBuffer: 4 * 1024 * 1024,
  }));
}

async function boot(page: Page, data: Fixture, start = 0) {
  let cursor = start;
  let current: CommandResult = start ? data.batches[start - 1] : { snapshot: data.initial, events: [] };
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.route("**/api/auth/config", (route) => route.fulfill({ json: { configured: false } }));
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    const post = route.request().method() === "POST";
    const body = post ? route.request().postDataJSON() : null;
    let json: unknown;
    if (url.pathname.endsWith("/guest")) json = { ready: true };
    else if (url.pathname.endsWith("/me")) json = {
      name: "You", preferences: defaultPreferences, authenticated: false, auth_available: false,
      table_defaults: defaults, ...(body || {}),
    };
    else if (url.pathname.endsWith("/sessions")) json = { sessions: [{
      id: data.initial.id, status: "active", hands: 2, profit: 0,
      created_at: data.initial.created_at, config: data.initial.config,
    }], next_cursor: null };
    else if (url.pathname.endsWith("/commands")) {
      requests.push(body.kind);
      current = data.batches[cursor++];
      if (!current) throw new Error("Unexpected extra command");
      json = current;
    } else if (url.pathname.includes("/sessions/")) json = {
      snapshot: current.snapshot,
      events: data.replays.find((replay) => replay.hand.number === current.snapshot.hand_number)?.events
        .filter((event) => event.id <= current.snapshot.last_event_id) || [],
    };
    else if (url.pathname.endsWith("/hands")) json = { hands: data.replays.map((replay) => replay.hand), next_cursor: null };
    else if (url.pathname.includes("/hands/")) json = data.replays.find((replay) => url.pathname.endsWith(replay.hand.id));
    else throw new Error(`Unexpected fixture request: ${url.pathname}`);
    return route.fulfill({ json });
  });
  await page.goto("/");
  await expect(page).toHaveTitle("Deepstack");
  await expect(page.getByRole("region", { name: "Poker table", exact: true })).toBeVisible();
  await page.getByLabel("Presentation speed").selectOption("manual");
  return { requests, errors };
}

const tableSelector = ".play-workspace .table-stage";
async function finishMotion(page: Page) {
  await page.evaluate(() => document.getAnimations().filter((animation) => animation.effect?.getComputedTiming().endTime !== Infinity).forEach((animation) => animation.finish()));
}

for (const [players, scenario] of [[2, "checkdown"], [6, "checkdown"], [9, "checkdown"], [2, "fold"], [3, "side-pot"]] as const) {
  for (const width of [1440, 390]) {
    test(`${players}-seat ${scenario} presents two complete hands without stale cards or repeated motion at ${width}px`, async ({ page }) => {
      const data = fixture(players, scenario);
      if (scenario === "side-pot") {
        expect(data.replays[0].events.some((event) => event.view.pots.length > 1)).toBe(true);
        expect(data.replays[0].events.some((event) => event.view.seats.filter((seat) => seat.winnings > 0).length > 1)).toBe(true);
      }
      await page.setViewportSize({ width, height: 900 });
      const { errors } = await boot(page, data);
      const table = page.locator(tableSelector);
      const seen: typeof data.batches[number]["events"] = [];
      let hand = 0;
      let before = data.initial;
      for (const batch of data.batches) {
        if (batch.snapshot.hand_number !== hand) {
          await page.getByRole("button", { name: hand ? "Next Hand" : "Deal first hand", exact: true }).click();
          seen.length = 0;
          hand = batch.snapshot.hand_number;
        } else {
          const controls = page.getByRole("region", { name: "Betting controls" });
          if (scenario === "fold" && before.legal.fold) await controls.getByRole("button", { name: "Fold", exact: true }).click();
          else if (scenario === "side-pot" && before.legal.max_raise_to) {
            await page.getByRole("button", { name: "All-in", exact: true }).click();
            await page.locator(".raise-button").click();
          } else await controls.getByRole("button", { name: /^(Call |Check$)/ }).click();
        }
        before = batch.snapshot;
        for (const [index, event] of batch.events.entries()) {
          if (index) await page.getByRole("button", { name: "Next action", exact: true }).click();
          await expect(table).toHaveAttribute("data-event-id", String(event.id));
          seen.push(event);
          await expect(table.locator(".board .playing-card")).toHaveCount(event.view.board.length);
          await expect(table.locator(".board > *")).toHaveCount(5);
          for (const seat of event.view.seats) {
            const dealt = seen.filter((e) => e.kind === "deal" && e.seat === seat.seat).length;
            const cards = seat.cards.length || (seat.in_hand && !event.view.complete ? Math.min(2, dealt) : 0);
            await expect(table.locator(`.seat-${seat.seat} .playing-card`)).toHaveCount(cards);
          }
          // Previously settled cards must survive later events without replaying entrance motion.
          expect(await table.locator(".playing-card[data-settled]").evaluateAll((cards) =>
            cards.flatMap((card) => card.getAnimations()).filter((animation) => animation.playState === "running").length,
          )).toBe(0);
          await expect(table.locator(".winner .wager:not(.awarded)")).toHaveCount(0);
          const pot = event.view.complete
            ? event.view.seats.reduce((total, seat) => total + seat.winnings, 0) : event.view.pot;
          await expect(table.locator(".pot strong")).toHaveText(money(pot));
          await finishMotion(page);
          await table.locator(".playing-card").evaluateAll((cards) => cards.forEach((card) => card.setAttribute("data-settled", "true")));
        }
      }
      await expect(page.getByRole("button", { name: "Next Hand", exact: true })).toBeEnabled();
      await page.reload();
      await expect(table.locator(".nameplate")).toHaveCount(players);
      expect(await table.locator(".playing-card").evaluateAll((cards) => cards.flatMap((card) => card.getAnimations()).length)).toBe(0);
      expect(await table.locator(".awarded").evaluateAll((nodes) => nodes.map((node) => getComputedStyle(node).opacity))).toEqual(
        await table.locator(".awarded").evaluateAll((nodes) => nodes.map(() => "0")),
      );
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: `/tmp/deepstack-flow-${players}-${scenario}-${width}.png` });
      expect(errors).toEqual([]);
    });
  }
}

test("replay scrubbing is static and respects the deal order", async ({ page }) => {
  const data = fixture(6);
  const { errors } = await boot(page, data);
  await page.getByRole("button", { name: "Review", exact: true }).click();
  const table = page.getByRole("region", { name: "Hand replay table" });
  const slider = page.getByLabel("Replay action", { exact: true });
  await expect(slider).toBeVisible();
  await slider.focus();
  await slider.press("Home");
  const replay = data.replays[0];
  for (const [index, event] of replay.events.entries()) {
    if (index) await page.getByRole("button", { name: "Next replay action", exact: true }).click();
    await expect(table).toHaveAttribute("data-event-id", String(event.id));
    for (const seat of event.view.seats) {
      const dealt = replay.events.slice(0, index + 1).filter((e) => e.kind === "deal" && e.seat === seat.seat).length;
      const cards = seat.cards.length || (seat.in_hand && !event.view.complete ? Math.min(2, dealt) : 0);
      await expect(table.locator(`.seat-${seat.seat} .playing-card`)).toHaveCount(cards);
    }
    expect(await table.locator(".playing-card, .wager").evaluateAll((nodes) => nodes.flatMap((node) => node.getAnimations()).length)).toBe(0);
  }
  await expect(page.getByRole("button", { name: "Restart replay" })).toBeVisible();
  await page.getByRole("button", { name: "Restart replay" }).click();
  await expect(table).toHaveAttribute("data-event-id", String(replay.events[0].id));
  await expect(table.locator(".hole-cards .playing-card")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("automatic checkpoints finish collection and respect pause, Review and hidden tabs", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-02T12:00:00Z") });
  await page.clock.pauseAt(new Date("2026-11-02T12:00:01Z"));
  const data = fixture(2);
  const batch = data.batches[1];
  const cut = batch.events.findIndex((event) => event.kind === "collect");
  expect(cut).toBeGreaterThanOrEqual(0);
  const collect = batch.events[cut];
  data.batches.splice(1, 1, {
    snapshot: { ...batch.snapshot, ...collect.view, needs_advance: true, last_event_id: collect.id },
    events: batch.events.slice(0, cut + 1),
  }, { ...batch, events: batch.events.slice(cut + 1) });
  const { requests, errors } = await boot(page, data, 1);
  await page.getByLabel("Presentation speed").selectOption("brisk");
  await page.getByRole("region", { name: "Betting controls" }).getByRole("button", { name: /^Call / }).click();
  const table = page.locator(tableSelector);
  await expect(table).toHaveAttribute("data-event-id", String(batch.events[0].id));
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await page.clock.runFor(10000);
  await expect(table).toHaveAttribute("data-event-id", String(batch.events[0].id));
  await page.getByRole("button", { name: "Play", exact: true }).click();
  for (let index = 0; index < cut; index++) {
    await page.clock.runFor(eventDuration(batch.events[index], "brisk"));
    await expect(table).toHaveAttribute("data-event-id", String(batch.events[index + 1].id));
  }
  await expect(table.locator(".wager:not(.awarded)")).toHaveCount(2);
  await page.clock.runFor(449);
  expect(requests).toEqual(["act"]);
  await page.getByRole("button", { name: "Pause playback" }).click();
  await page.clock.runFor(10000);
  expect(requests).toEqual(["act"]);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.getByRole("button", { name: "Resume playback" }).click();
  await page.clock.runFor(10000);
  expect(requests).toEqual(["act"]);
  await page.evaluate(() => {
    const schedule = window.setTimeout;
    window.setTimeout = ((handler, delay, ...args) => {
      if (delay === 450) document.documentElement.dataset.collectionScheduled = "true";
      return schedule(handler, delay, ...args);
    }) as typeof window.setTimeout;
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  // Wait for React to schedule the resumed timer before moving the fake clock.
  await expect(page.locator("html")).toHaveAttribute("data-collection-scheduled", "true");
  await page.clock.runFor(449);
  expect(requests).toEqual(["act"]);
  await page.clock.runFor(1);
  await expect(table).toHaveAttribute("data-event-id", String(batch.events[cut + 1].id));
  expect(requests).toEqual(["act", "advance"]);
  await expect(table.locator(".wager:not(.awarded)")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("reduced motion keeps deliberate event pacing", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-02T12:00:00Z") });
  await page.clock.pauseAt(new Date("2026-11-02T12:00:01Z"));
  await page.emulateMedia({ reducedMotion: "reduce" });
  const data = fixture(6);
  const { errors } = await boot(page, data);
  await page.getByLabel("Presentation speed").selectOption("deliberate");
  await page.getByRole("button", { name: "Deal first hand", exact: true }).click();
  const table = page.locator(tableSelector);
  const events = data.batches[0].events;
  await expect(table).toHaveAttribute("data-event-id", String(events[0].id));
  await page.clock.runFor(eventDuration(events[0], "deliberate") - 1);
  await expect(table).toHaveAttribute("data-event-id", String(events[0].id));
  await page.clock.runFor(1);
  await expect(table).toHaveAttribute("data-event-id", String(events[1].id));
  await page.clock.runFor(eventDuration(events[1], "deliberate"));
  await expect(table.locator(".hole-cards .playing-card")).toHaveCount(1);
  expect(await table.locator(".playing-card").evaluateAll((cards) => cards.every((card) =>
    Number.parseFloat(getComputedStyle(card).animationDuration) <= 0.00001,
  ))).toBe(true);
  expect(errors).toEqual([]);
});

test("opening player details during an all-in never reveals the future settled stack", async ({ page }) => {
  const data = fixture(3, "side-pot");
  const { errors } = await boot(page, data, 1);
  await page.getByRole("button", { name: "All-in", exact: true }).click();
  await page.locator(".raise-button").click();
  const first = data.batches[1].events[0];
  const table = page.locator(tableSelector);
  await expect(table).toHaveAttribute("data-event-id", String(first.id));
  expect(first.view.seats[0].stack).not.toBe(data.batches[1].snapshot.seats[0].stack);
  await table.locator(".hero-seat .nameplate").click();
  await expect(page.getByRole("dialog").locator(".account-identity p")).toContainText(money(first.view.seats[0].stack));
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await expect(table).toHaveAttribute("data-event-id", String(first.id));
  expect(errors).toEqual([]);
});
