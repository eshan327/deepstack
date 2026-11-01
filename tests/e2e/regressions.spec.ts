import { test, expect, type Page } from "@playwright/test";
import { defaults, type Snapshot } from "../../apps/web/lib/api";
import { defaultPreferences } from "../../apps/web/lib/presentation";

const sid = "00000000-0000-4000-8000-000000000001";
const older = "00000000-0000-4000-8000-000000000002";
const hid = "00000000-0000-4000-8000-000000000003";
const snapshot: Snapshot = {
  id: sid, version: 0, status: "active",
  config: { ...defaults, players: 2, seat_stacks: null }, hand_number: 0, street: "Ready",
  board: [], pot: 0, pots: [], actor: null, complete: true, message: "Ready",
  legal: { fold: false, check: false, call: null, min_raise_to: null, max_raise_to: null, presets: [] },
  needs_advance: false, last_event_id: 0, hands_played: 0, profit: 0,
  buy_ins: 60000, cash_outs: 0, created_at: "2026-01-01T00:00:00Z",
  seats: ["You", "Maya"].map((name, seat) => ({
    seat, name, stack: 60000, starting_stack: 60000, bet: 0, cards: [],
    in_hand: false, folded: false, sitting_out: false, dealer: seat === 0,
    blind: null, position: seat === 0 ? "BTN" : "BB", last_action: "", winnings: 0, note: "",
    observed: { hands: 0, vpip: 0, pfr: 0, three_bet: 0, three_bet_opportunities: 0,
      bets_raises: 0, calls: 0, folds_to_bet: 0, faced_bet: 0 },
  })),
};
const preflop = {
  ...snapshot, hand_number: 1, street: "Preflop", actor: 0, complete: false,
  pot: 300, message: "Your turn.",
  seats: snapshot.seats.map((s) => ({ ...s, in_hand: true, cards: s.seat ? [] : ["As", "Qh"] })),
};
const flop = { ...preflop, street: "Flop", board: ["2c", "3d", "7h"], pot: 600 };
const hand = {
  id: hid, session_id: sid, number: 1, board: flop.board, hero_cards: ["As", "Qh"],
  profit: 100, pot: 600, created_at: snapshot.created_at, position: "BTN",
  big_blind: 200, players: 2, bookmarked: false, note: "",
};
const replay = {
  hand,
  events: [
    { id: 1, kind: "action", action: "check", text: "You: Check", view: preflop },
    { id: 2, kind: "board", text: "Flop", view: flop },
  ],
  decisions: [preflop, flop].map((view, i) => ({
    event_id: i + 1, view, legal: { ...snapshot.legal, check: true },
    effective_stack: 60000, big_blind: 200, action: { kind: "check" }, side_pots: false,
  })),
};
const analysis = {
  method: "monte_carlo", win: 0.65, tie: 0.1, loss: 0.25,
  range_combos: { 1: 990 }, made_hand: "High card", call_ev: null, spr: 100,
  equity: 0.7, uncertainty: 0.05, samples: 2048, call_threshold: null,
  call_amount: 0, pot: 600, effective_stack: 60000, ranges: {}, explanation: "Flop estimate.",
};

async function mockApp(page: Page, opened = true) {
  const profile = {
    name: "You", preferences: defaultPreferences, authenticated: false, auth_available: false,
    table_defaults: { ...defaults, players: 2, seat_stacks: [10000, 20000] },
  };
  const summary = (id: string) => ({
    id, status: "active", hands: 1, profit: 100,
    created_at: snapshot.created_at, config: snapshot.config,
  });
  await page.route("**/api/auth/config", (route) => route.fulfill({ json: { configured: false } }));
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    const post = route.request().method() === "POST";
    const body = post ? route.request().postDataJSON() : null;
    let json: unknown;
    if (path === "/guest") json = { ready: true };
    else if (path === "/me") json = post ? { ...profile, ...body } : profile;
    else if (path === "/sessions" && post)
      json = { snapshot: { ...snapshot, config: body.config }, events: [] };
    else if (path === "/sessions")
      json = url.searchParams.has("before")
        ? { sessions: [summary(older)], next_cursor: null }
        : { sessions: opened ? [summary(sid)] : [], next_cursor: url.searchParams.has("active") ? null : "older" };
    else if (path.startsWith("/sessions/"))
      json = { snapshot: { ...snapshot, id: path.split("/")[2] }, events: [] };
    else if (path === "/hands") json = { hands: [hand], next_cursor: null };
    else if (path === `/hands/${hid}`) json = replay;
    else if (path === `/hands/${hid}/annotation`) json = { ...hand, ...body };
    else if (path === `/hands/${hid}/analysis`) json = analysis;
    else if (path === "/ranges/expand") {
      if (!body.range.trim()) return route.fulfill({ status: 422, json: { detail: "Empty range" } });
      json = { hands: body.range === "random" ? ["AA", "KK"] : body.range.split(",").map((s: string) => s.trim()) };
    } else return route.fulfill({ status: 404, json: { detail: "Unexpected test request" } });
    await route.fulfill({ json });
  });
}

async function openReview(page: Page) {
  await mockApp(page);
  await page.goto("/");
  await expect(page).toHaveTitle("Deepstack");
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await expect(page.getByLabel("Jump to your decision")).toBeVisible();
}

test("a save response never marks a newer note draft as saved", async ({ page }) => {
  await openReview(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const writes: string[] = [];
  await page.route(`**/hands/${hid}/annotation`, async (route) => {
    const body = route.request().postDataJSON();
    writes.push(body.note);
    await gate;
    await route.fulfill({ json: { ...hand, ...body } });
  });
  const form = page.locator(".study-note");
  const note = page.getByLabel("Study note", { exact: true });
  await note.fill("Submitted draft");
  await form.getByRole("button", { name: "Save note", exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  await note.fill("Newer unsaved draft");
  const response = page.waitForResponse(`**/hands/${hid}/annotation`);
  release();
  await response;
  await expect(form.getByRole("button", { name: "Save note", exact: true })).toBeEnabled();
  await expect(note).toHaveValue("Newer unsaved draft");
  await form.getByRole("button", { name: "Save note", exact: true }).click();
  await expect(form.getByRole("button", { name: "Saved", exact: true })).toBeEnabled();
  expect(writes).toEqual(["Submitted draft", "Newer unsaved draft"]);
});

for (const jump of ["decision", "street"]) {
  test(`analysis recovers after a ${jump} change during a request`, async ({ page }) => {
    await openReview(page);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let requests = 0;
    await page.route(`**/hands/${hid}/analysis`, async (route) => {
      requests++;
      if (route.request().postDataJSON().decision === 0) {
        await gate;
        await route.fulfill({ json: { ...analysis, equity: 0.1 } });
      } else await route.fulfill({ json: analysis });
    });
    await page.getByRole("button", { name: "Analyze decision", exact: true }).click();
    await expect.poll(() => requests).toBe(1);
    if (jump === "decision") await page.getByLabel("Jump to your decision").selectOption("1");
    else await page.locator(".street-tabs").getByRole("button", { name: "Flop", exact: true }).click();
    await expect(page.getByRole("button", { name: "Analyze decision", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Analyze decision", exact: true }).click();
    await expect(page.locator(".equity-result")).toContainText("70.0%");
    const stale = page.waitForResponse((r) => r.url().endsWith("/analysis") && r.request().postDataJSON().decision === 0);
    release();
    await stale;
    await expect(page.getByRole("button", { name: "Recalculate", exact: true })).toBeEnabled();
    await expect(page.locator(".equity-result")).toContainText("70.0%");
  });
}

test("an empty range grid stays editable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") errors.push(message.text());
  });
  await openReview(page);
  await page.locator(".review-ranges summary").click();
  const range = page.getByLabel("Maya range", { exact: true });
  await range.fill("AA");
  await page.getByRole("button", { name: "Edit range grid", exact: true }).click();
  const grid = page.locator(".range-grid");
  const aces = grid.getByRole("button", { name: "AA", exact: true });
  await expect(aces).toHaveAttribute("aria-pressed", "true");
  await aces.click();
  await expect(range).toHaveValue("");
  const kings = grid.getByRole("button", { name: "KK", exact: true });
  await expect(kings).toBeEnabled();
  await kings.click();
  await expect(range).toHaveValue("KK");
  await expect(kings).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
  await grid.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "/tmp/deepstack-qa/audit-range-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(kings).toBeVisible();
  await grid.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "/tmp/deepstack-qa/audit-range-phone.png" });
  expect(errors).toEqual([]);
});

test("new tables restore saved individual starting stacks", async ({ page }) => {
  await mockApp(page, false);
  let stacks: number[] | undefined;
  await page.route("**/api/v1/sessions", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const config = route.request().postDataJSON().config;
    stacks = config.seat_stacks;
    await route.fulfill({ json: { snapshot: { ...snapshot, config }, events: [] } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Set up your table", exact: true }).click();
  await expect(page.getByLabel("Individual starting stacks")).toBeChecked();
  await expect(page.getByLabel("You ($)", { exact: true })).toHaveValue("100");
  await expect(page.getByLabel("Seat 2 ($)", { exact: true })).toHaveValue("200");
  await page.getByRole("button", { name: "Start table", exact: true }).click();
  await expect.poll(() => stacks).toEqual([10000, 20000]);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("a stale retry is cleared so play can recover", async ({ page }) => {
  await mockApp(page);
  const commands: { command_id: string; expected_version: number }[] = [];
  await page.route("**/commands", async (route) => {
    commands.push(route.request().postDataJSON());
    if (commands.length === 1) return route.abort("failed");
    if (commands.length === 2) return route.fulfill({ status: 409, json: { detail: "Table changed" } });
    await route.fulfill({
      json: { snapshot: { ...preflop, version: 2, legal: { ...snapshot.legal, check: true } }, events: [] },
    });
  });
  await page.route(`**/sessions/${sid}`, (route) =>
    route.fulfill({ json: { snapshot: { ...snapshot, version: 1 }, events: [] } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Deal first hand", exact: true }).click();
  const retry = page.getByRole("button", { name: "Retry", exact: true });
  await expect(retry).toBeEnabled();
  await retry.click();
  await expect(page.locator("main").getByRole("alert")).toContainText("Table changed");
  await retry.click();
  await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "Deal first hand", exact: true }).click();
  await expect(page.getByRole("region", { name: "Betting controls" })).toBeVisible();
  expect(commands).toHaveLength(3);
  expect(commands[0].command_id).toBe(commands[1].command_id);
  expect(commands[2].command_id).not.toBe(commands[0].command_id);
  expect(commands[2].expected_version).toBe(1);
});

test("earlier tables can be loaded and resumed", async ({ page }) => {
  await openReview(page);
  await page.getByRole("button", { name: "Earlier tables", exact: true }).click();
  await expect(page.getByRole("button", { name: "Earlier tables", exact: true })).toHaveCount(0);
  await page.getByLabel("Filter session").selectOption(older);
  await page.getByRole("button", { name: "Resume this table", exact: true }).click();
  await expect(page.getByRole("button", { name: "Deal first hand", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("deepstack.session"))).toBe(older);
});

test("startup finds an old active table independently of recent history", async ({ page }) => {
  await mockApp(page);
  await page.route("**/api/v1/sessions?*", async (route) => {
    const active = new URL(route.request().url()).searchParams.get("active") === "true";
    await route.fulfill({ json: { sessions: [{
      id: active ? older : sid, status: active ? "active" : "ended", hands: 0,
      profit: 0, created_at: snapshot.created_at, config: snapshot.config,
    }], next_cursor: null } });
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Deal first hand", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("deepstack.session"))).toBe(older);
});


for (const width of [1440, 390]) {
  test(`analysis explains equity and call EV at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await openReview(page);
    await page.route(`**/hands/${hid}/analysis`, (route) => route.fulfill({ json: {
      ...analysis, method: width === 390 ? "exact" : "monte_carlo",
      uncertainty: width === 390 ? 0 : 0.05, call_threshold: 0.25, call_ev: 1800,
    } }));
    await page.getByRole("button", { name: "Analyze decision", exact: true }).click();
    const result = page.getByRole("region", { name: "Analysis results" });
    await expect(result).toBeVisible();
    await expect(result).toContainText("70.0%");
    await expect(result).toContainText("65.0%");
    await expect(result).toContainText("10.0%");
    await expect(result).toContainText("25.0%");
    await expect(result).toContainText("+$18");
    await expect(result).toContainText("no further betting");
    await expect(result).toContainText(width === 390 ? "Exact enumeration" : "Monte Carlo");
    if (width === 390) await expect(result).not.toContainText("±");
    await page.locator(".review-ranges summary").click();
    await expect(page.locator(".range-editor")).toContainText("990 combos");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await result.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/deepstack-qa/analysis-${width}.png`, fullPage: width > 390 });
    expect(errors).toEqual([]);
  });
}


test("bet sizing uses whole dollars and preserves an exact fractional all-in", async ({ page }) => {
  await mockApp(page);
  const legal = { ...snapshot.legal, fold: true, call: 200, min_raise_to: 451,
    max_raise_to: 1049, presets: [{ label: "Min", amount: 500 }, { label: "All-in", amount: 1049 }] };
  await page.route(`**/api/v1/sessions/${sid}`, (route) => route.fulfill({ json: {
    snapshot: { ...preflop, legal }, events: [],
  } }));
  let action: unknown;
  await page.route("**/commands", (route) => {
    action = route.request().postDataJSON().action;
    return route.fulfill({ json: { snapshot: { ...preflop, legal }, events: [] } });
  });
  await page.goto("/");
  const input = page.getByRole("textbox", { name: "Raise to amount" });
  await expect(input).toHaveValue("5");
  await expect(page.getByRole("slider", { name: "Bet size", exact: true })).toHaveAttribute("step", "100");
  await input.fill("5.50");
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator(".raise-button")).toBeDisabled();
  await input.fill("6");
  await expect(page.locator(".raise-button")).toHaveText("Raise to $6");
  await page.locator(".raise-button").click();
  expect(action).toEqual({ kind: "raise_to", amount: 600 });
  await page.getByRole("button", { name: "All-in", exact: true }).click();
  await expect(input).toHaveValue("10.49");
  await expect(page.locator(".raise-button")).toBeEnabled();
  await page.locator(".raise-button").click();
  expect(action).toEqual({ kind: "raise_to", amount: 1049 });
});

for (const width of [1440, 390]) {
  test(`showdown cards stay visible through awards and hand completion at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.setViewportSize({ width, height: 900 });
    await mockApp(page);
    await page.route(`**/api/v1/sessions/${sid}`, (route) => route.fulfill({ json: {
      snapshot: { ...flop, legal: { ...snapshot.legal, check: true } }, events: [],
    } }));
    const shown = {
      ...flop, actor: null,
      seats: flop.seats.map((seat) => ({ ...seat, cards: seat.seat ? ["Kc", "Kh"] : seat.cards })),
    };
    const complete = { ...shown, complete: true, street: "Complete", message: "Maya wins." };
    await page.route("**/commands", (route) => route.fulfill({ json: {
      snapshot: complete,
      events: [
        { id: 1, kind: "show", seat: 1, text: "Maya shows Kc Kh", view: shown },
        { id: 2, kind: "award", seat: 1, text: "Maya wins", view: shown },
        { id: 3, kind: "complete", text: "Hand complete", view: complete },
      ],
    } }));
    await page.goto("/");
    await expect(page).toHaveTitle("Deepstack");
    await page.getByLabel("Presentation speed").selectOption("manual");
    await page.getByRole("button", { name: "Check", exact: true }).click();
    const next = page.getByRole("button", { name: "Next action", exact: true });
    const table = page.getByRole("region", { name: "Poker table", exact: true });
    const cards = table.locator(".seat-1 .playing-card");
    await next.click();
    await expect(table).toHaveAttribute("data-event", "show");
    await expect(cards).toHaveCount(2);
    await cards.evaluateAll((nodes) => {
      nodes.forEach((card) => card.getAnimations().forEach((animation) => animation.finish()));
    });
    for (const kind of ["award", "complete"]) {
      await next.click();
      await expect(table).toHaveAttribute("data-event", kind);
      // A settled card must never start a new fade when the event changes.
      expect(await cards.evaluateAll((nodes) => nodes.map((card) => getComputedStyle(card).opacity))).toEqual(["1", "1"]);
      expect(await cards.evaluateAll((nodes) => nodes.flatMap((card) => card.getAnimations()).filter((animation) => animation.playState === "running").length)).toBe(0);
    }
    await expect(page.getByRole("button", { name: "Next Hand", exact: true })).toBeEnabled();
    await page.screenshot({ path: `/tmp/deepstack-showdown-${width}.png` });
    expect(errors).toEqual([]);
  });
}
