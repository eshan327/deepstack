import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";

const qa = "/tmp/deepstack-qa";
mkdirSync(qa, { recursive: true });

async function create(page: Page, config: Record<string, unknown> = {}) {
  expect(
    (await page.request.post("/api/v1/guest", { data: {} })).ok(),
  ).toBeTruthy();
  const response = await page.request.post("/api/v1/sessions", {
    data: { command_id: crypto.randomUUID(), config },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).snapshot;
}

function seed(sid: string, scenario: string) {
  execFileSync(
    "uv",
    ["run", "python", "-m", "tests.seed_browser", sid, scenario],
    {
      cwd: path.join(process.cwd(), "apps/api"),
      stdio: "pipe",
    },
  );
}

async function current(page: Page, id: string) {
  return (await (await page.request.get(`/api/v1/sessions/${id}`)).json())
    .snapshot;
}

async function drain(page: Page) {
  for (let i = 0; i < 100; i++) {
    if (
      await page.getByRole("region", { name: "Betting controls" }).isVisible()
    )
      return;
    const next = page.getByRole("button", {
      name: /^(Next Hand|Rebuy|Deal first hand)$/,
    });
    if ((await next.isVisible()) && (await next.isEnabled())) return;
    await page.clock.runFor(2500);
    await page.waitForTimeout(20);
  }
  throw new Error("Presentation did not reach a decision or hand completion.");
}

async function finish(page: Page) {
  for (let i = 0; i < 50; i++) {
    await drain(page);
    if (
      await page
        .getByRole("button", { name: /^(Next Hand|Rebuy)$/ })
        .isVisible()
    )
      return;
    const response = page.waitForResponse(
      (r) => r.url().endsWith("/commands") && r.request().method() === "POST",
    );
    await page
      .getByRole("region", { name: "Betting controls" })
      .getByRole("button", { name: /^(Call |Check$)/ })
      .click();
    expect((await response).ok()).toBeTruthy();
  }
  throw new Error("Hand did not finish.");
}

async function noOverlap(page: Page) {
  const overlaps = await page
    .locator(".play-workspace .nameplate")
    .evaluateAll((nodes) => {
      const boxes = nodes.map((n) => n.getBoundingClientRect());
      return boxes.some((a, i) =>
        boxes
          .slice(i + 1)
          .some(
            (b) =>
              a.left < b.right &&
              a.right > b.left &&
              a.top < b.bottom &&
              a.bottom > b.top,
          ),
      );
    });
  expect(overlaps).toBe(false);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}

test.beforeEach(async ({ page }) => {
  await page.clock.install();
});

test("account bootstrap fetches a JWT despite the SDK session cache", async ({
  page,
}) => {
  await page.request.post("/api/v1/guest", { data: {} });
  const guest = await (await page.request.get("/api/v1/me")).json();
  let signedIn = true;
  let tokens = 0;
  const authorization: (string | undefined)[] = [];
  await page.route("**/api/auth/config", (route) =>
    route.fulfill({ json: { configured: true } }),
  );
  await page.route("**/api/auth/get-session**", (route) =>
    route.fulfill({
      json: signedIn
        ? {
            session: {
              id: "qa",
              token: "opaque-session",
              userId: "qa",
              expiresAt: "2099-01-01T00:00:00Z",
              createdAt: "2026-01-01T00:00:00Z",
              updatedAt: "2026-01-01T00:00:00Z",
            },
            user: {
              id: "qa",
              name: "QA",
              email: "qa@example.invalid",
              emailVerified: true,
              createdAt: "2026-01-01T00:00:00Z",
              updatedAt: "2026-01-01T00:00:00Z",
            },
          }
        : null,
    }),
  );
  await page.route("**/api/auth/token", (route) => {
    tokens++;
    return route.fulfill({ json: { token: "qa-jwt" } });
  });
  await page.route("**/api/auth/sign-out", (route) => {
    signedIn = false;
    return route.fulfill({ json: { success: true } });
  });
  await page.route("**/api/v1/me**", (route) => {
    if (signedIn) authorization.push(route.request().headers().authorization);
    return route.fulfill({
      json: {
        ...guest,
        name: signedIn ? "QA" : "You",
        authenticated: signedIn,
        auth_available: true,
      },
    });
  });
  await page.route("**/api/v1/sessions", (route) =>
    route.fulfill({ json: { sessions: [] } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Your account" }).click();
  await expect(
    page.getByText("History saved to your account", { exact: true }),
  ).toBeVisible();
  expect(tokens).toBeGreaterThan(0);
  expect(authorization.length).toBeGreaterThanOrEqual(2);
  expect(authorization.every((header) => header === "Bearer qa-jwt")).toBe(
    true,
  );
  const reloaded = page.waitForEvent("load");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await reloaded;
  await page.getByRole("button", { name: "Your account" }).click();
  await expect(page.getByText("Guest profile", { exact: true })).toBeVisible();
});

test("setup, profile, play, notes, history, coaching and export survive refresh", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Your account" }).click();
  await page.getByLabel("Display name").fill("Eshan");
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Profile saved" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Set up your table" }).click();
  await page.getByLabel("Small blind ($)", { exact: true }).fill("5");
  await page.getByRole("button", { name: "Start table", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "small blind cannot exceed",
  );
  await page.getByLabel("Small blind ($)", { exact: true }).fill("1");
  await page.getByRole("button", { name: "Start table", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Deal first hand" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Deal first hand" }).click();
  await drain(page);
  await expect(
    page.getByRole("textbox", { name: "Raise to amount" }),
  ).not.toHaveValue("");
  await finish(page);
  const sessions = await (await page.request.get("/api/v1/sessions")).json();
  const sid = sessions.sessions[0].id;
  const before = await current(page, sid);
  const names = await page
    .locator(".play-workspace .seat-name")
    .allTextContents();
  expect(names[0]).toBe("Eshan");
  await page.reload();
  await expect(
    page.getByRole("button", { name: /^(Next Hand|Rebuy)$/ }),
  ).toBeVisible();
  expect(await current(page, sid)).toEqual(before);
  expect(
    await page.locator(".play-workspace .seat-name").allTextContents(),
  ).toEqual(names);
  await page.locator('.play-workspace [data-seat="1"] .nameplate').click();
  await page
    .getByRole("textbox", { name: "Notes", exact: true })
    .fill("Observed small flop sizing.");
  await page.getByRole("button", { name: "Save note", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  const beforeReview = await current(page, sid);
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await expect(page.locator(".hand-row")).toHaveCount(1);
  await expect(
    page.getByRole("slider", { name: "Replay action" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Save hand", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Unsave hand", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Study note", exact: true })
    .fill("Consider position before calling.");
  await page
    .locator(".study-note")
    .getByRole("button", { name: "Save note", exact: true })
    .click();
  await expect(
    page
      .locator(".study-note")
      .getByRole("button", { name: "Saved", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Analyze decision", exact: true })
    .click();
  await expect(page.locator(".equity-result")).toContainText("Equity");
  await expect(page.locator(".equity-result")).toContainText("samples");
  await page.locator(".export-menu summary").click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Text history", exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/deepstack-\d+\.txt/);
  await page.screenshot({ path: `${qa}/review-desktop.png`, fullPage: true });
  await page.getByRole("button", { name: "Resume table", exact: true }).click();
  expect(await current(page, sid)).toEqual(beforeReview);
  expect(errors).toEqual([]);
});

test("pause, manual steps, readable pacing and reduced motion retain every action", async ({
  page,
}) => {
  await create(page, { players: 6 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Deal first hand" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Action log", exact: true }).click();
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/commands") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Deal first hand" }).click();
  expect((await response).ok()).toBeTruthy();
  await page.getByRole("button", { name: "Pause playback" }).click();
  const before = await page.locator(".live-action-rail .log-row").count();
  await page.clock.runFor(20_000);
  expect(await page.locator(".live-action-rail .log-row").count()).toBe(before);
  await expect(
    page.getByRole("region", { name: "Betting controls" }),
  ).toBeHidden();
  await page.getByRole("button", { name: "Next action", exact: true }).click();
  await page.clock.runFor(20_000);
  expect(
    await page.locator(".live-action-rail .log-row").count(),
  ).toBeGreaterThanOrEqual(before);
  await page.getByRole("button", { name: "Your account" }).click();
  await page.getByRole("switch", { name: "Reduce motion" }).check();
  await page.getByRole("button", { name: "Close panel" }).click();
  await page.getByRole("button", { name: "Resume playback" }).click();
  await drain(page);
  const retained = await page.locator(".live-action-rail .log-row").count();
  expect(retained).toBeGreaterThan(1);
  await page.getByRole("button", { name: "Close action log" }).click();
  await expect(page.locator(".live-action-rail")).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Betting controls" }),
  ).toBeVisible();
  await expect(page.locator(".live-action-rail")).toHaveCount(0);
  await page.getByRole("button", { name: "Action log", exact: true }).click();
  expect(await page.locator(".live-action-rail .log-row").count()).toBe(
    retained,
  );
});

test("lost response retries settle an actual all-in side pot once", async ({
  page,
}) => {
  const s = await create(page, {
    players: 3,
    seat_stacks: [60000, 20000, 40000],
  });
  seed(s.id, "side-pot");
  await page.goto("/");
  await expect(
    page.getByRole("region", { name: "Betting controls" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "All-in", exact: true }).click();
  let calls = 0;
  await page.route("**/commands", async (route) => {
    if (calls++ === 0) {
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: /^Raise to \$600/ }).click();
  await expect(
    page.getByRole("button", { name: "Retry", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await drain(page);
  const result = await current(page, s.id);
  expect(result.seats[0].stack).toBe(120000);
  expect(result.hands_played).toBe(1);
  expect(result.profit).toBe(60000);
  await page.screenshot({ path: `${qa}/side-pot.png` });
});

test("manual pacing and hidden tabs wait; player notes preserve a drafted raise", async ({
  page,
}) => {
  await create(page, { players: 6 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Deal first hand" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Action log", exact: true }).click();
  await page.getByLabel("Presentation speed").selectOption("manual");
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/commands") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Deal first hand" }).click();
  expect((await response).ok()).toBeTruthy();
  await page.clock.runFor(30_000);
  await expect(
    page.getByRole("region", { name: "Betting controls" }),
  ).toBeHidden();
  expect(await page.locator(".live-action-rail .log-row").count()).toBe(0);
  await page.getByRole("button", { name: "Next action", exact: true }).click();
  expect(await page.locator(".live-action-rail .log-row").count()).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.getByLabel("Presentation speed").selectOption("brisk");
  await page.clock.runFor(30_000);
  expect(await page.locator(".live-action-rail .log-row").count()).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await drain(page);
  const amount = page.getByRole("textbox", { name: "Raise to amount" });
  await amount.fill("123.45");
  await page.locator('.play-workspace [data-seat="1"] .nameplate').click();
  await page
    .getByRole("textbox", { name: "Notes", exact: true })
    .fill("Watch the sizing.");
  await page.getByRole("button", { name: "Save note", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close panel" }).click();
  await expect(amount).toHaveValue("123.45");
});

for (let players = 2; players <= 9; players++) {
  test(`${players} seats keep wagers clear of cards, labels and pot`, async ({
    page,
  }) => {
    const s = await create(page, { players });
    const deck = [..."cdhs"].flatMap((suit) =>
      [..."A23456789TJQK"].map((rank) => rank + suit),
    );
    const fixture = {
      ...s,
      hand_number: 1,
      street: "River",
      complete: false,
      actor: 0,
      pot: 12345600,
      board: deck.slice(18, 23),
      pots: [],
      needs_advance: false,
      seats: s.seats.map((seat: Record<string, unknown>, i: number) => ({
        ...seat,
        in_hand: true,
        folded: false,
        stack: 9876500,
        bet: 1234500,
        cards: deck.slice(i * 2, i * 2 + 2),
        position: [
          "BTN",
          "SB",
          "BB",
          "UTG",
          "UTG+1",
          "UTG+2",
          "LJ",
          "HJ",
          "CO",
        ][i],
        last_action: "Call $12,345",
        winnings: 0,
      })),
    };
    await page.route(`**/api/v1/sessions/${s.id}`, (route) =>
      route.fulfill({ json: { snapshot: fixture, events: [] } }),
    );
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.locator(".play-workspace .wager")).toHaveCount(players);
    for (const viewport of [
      { width: 1600, height: 1000 },
      { width: 1280, height: 720 },
      { width: 1024, height: 768 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      for (let log = 0; log < (viewport.width > 1200 ? 2 : 1); log++) {
        await page.clock.runFor(50);
        await page.waitForTimeout(50);
        const collisions = await page
          .locator(".play-workspace .table-stage")
          .evaluate((root) => {
            const intersects = (a: DOMRect, b: DOMRect) =>
              a.left < b.right - 1 &&
              a.right > b.left + 1 &&
              a.top < b.bottom - 1 &&
              a.bottom > b.top + 1;
            const visible = (selector: string) =>
              [...root.querySelectorAll(selector)].filter((n) => {
                const style = getComputedStyle(n);
                return style.visibility !== "hidden" && style.opacity !== "0";
              });
            const protectedNodes = visible(
              ".pot > span, .pot strong, .board, .seat-details, .hole-cards .playing-card, .monogram",
            );
            const result: string[] = [];
            for (const wager of visible(".wager:not(.awarded)"))
              for (const node of protectedNodes) {
                if (
                  intersects(
                    wager.getBoundingClientRect(),
                    node.getBoundingClientRect(),
                  )
                )
                  result.push(
                    `seat ${wager.closest("[data-seat]")?.getAttribute("data-seat")} wager / ${node.className}`,
                  );
              }
            for (const center of visible(".board, .pot > span, .pot strong"))
              for (const node of visible(
                ".seat-details, .hole-cards .playing-card",
              )) {
                if (
                  intersects(
                    center.getBoundingClientRect(),
                    node.getBoundingClientRect(),
                  )
                )
                  result.push(
                    `${center.className} / seat ${node.closest("[data-seat]")?.getAttribute("data-seat")} ${node.className}: ${JSON.stringify(center.getBoundingClientRect().toJSON())} / ${JSON.stringify(node.getBoundingClientRect().toJSON())}`,
                  );
              }
            return result;
          });
        expect(
          collisions,
          `${players} players, ${viewport.width}×${viewport.height}, log ${log}`,
        ).toEqual([]);
        if (viewport.width > 1200)
          await page
            .getByRole("button", { name: "Action log", exact: true })
            .click();
      }
      if (players === 6)
        await page.screenshot({
          path: `${qa}/wagers-${viewport.width}.png`,
          animations: "disabled",
          fullPage: true,
        });
      if (players === 9 && viewport.width === 1024) {
        await page
          .getByRole("button", { name: "Action log", exact: true })
          .click();
        await expect(page.getByRole("dialog")).toBeVisible();
        await page.getByRole("button", { name: "Close panel" }).click();
      }
    }
  });
  test(`${players} seats fit desktop, small laptop and portrait phone`, async ({
    page,
  }) => {
    await create(page, { players });
    await page.goto("/");
    await expect(
      page.getByRole("button", { name: "Deal first hand" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Deal first hand" }).click();
    await drain(page);
    await expect(page.locator(".play-workspace .nameplate")).toHaveCount(
      players,
    );
    for (const viewport of [
      { width: 1600, height: 1000 },
      { width: 1440, height: 900 },
      { width: 1280, height: 720 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await noOverlap(page);
      if (viewport.width > 600)
        await expect(
          page.getByRole("region", { name: "Betting controls" }),
        ).toBeInViewport();
      const covered = await page.locator(".play-workspace").evaluate((root) => {
        const dock = root
          .querySelector(".action-dock")
          ?.getBoundingClientRect();
        return (
          dock &&
          [
            ...root.querySelectorAll(".nameplate, .hero-seat .playing-card"),
          ].some((n) => n.getBoundingClientRect().bottom > dock.top)
        );
      });
      expect(covered).toBeFalsy();
      if (players === 6 || players === 9)
        await page.screenshot({
          path: `${qa}/${players}-seats-${viewport.width}.png`,
          fullPage: true,
        });
    }
    await page.getByRole("button", { name: "Action log", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("button", { name: "Close panel" }).click();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole("button", { name: "Action log", exact: true }).click();
    await expect(page.locator(".live-action-rail")).toBeVisible();
    await noOverlap(page);
  });
}

test("nine-seat revealed cards and full board remain readable", async ({
  page,
}) => {
  const s = await create(page, { players: 9 });
  seed(s.id, "nine-max");
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: /^(Next Hand|Rebuy)$/ }),
  ).toBeVisible();
  await expect(page.locator(".board .playing-card")).toHaveCount(5);
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await noOverlap(page);
    await page.screenshot({
      path: `${qa}/nine-showdown-${viewport.width}.png`,
      fullPage: true,
    });
  }
});

test("table sounds opt in, persist, and do not replay on reload; cards deal seat by seat", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.addInitScript(() => {
    const observed = window as typeof window & { soundStarts: number };
    observed.soundStarts = 0;
    const oscillatorStart = OscillatorNode.prototype.start;
    OscillatorNode.prototype.start = function (when?: number) {
      observed.soundStarts++;
      oscillatorStart.call(this, when);
    };
    const bufferStart = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function (when?: number, offset?: number, duration?: number) {
      observed.soundStarts++;
      bufferStart.call(this, when, offset, duration);
    };
  });
  await create(page, { players: 6 });
  await page.goto("/");
  await expect(page).toHaveTitle("Deepstack");
  await expect(page.getByRole("button", { name: "Deal first hand" })).toBeVisible();
  await page.getByLabel("Presentation speed").selectOption("manual");
  await page.getByRole("button", { name: "Your account" }).click();
  const sounds = page.getByRole("switch", { name: "Table sounds" });
  await expect(sounds).not.toBeChecked();
  const saved = page.waitForResponse((r) => r.url().endsWith("/me") && r.request().method() === "POST" && r.request().postDataJSON().preferences.sounds);
  await sounds.check();
  expect((await saved).ok()).toBeTruthy();
  await page.getByRole("button", { name: "Close panel" }).click();
  const dealt = page.waitForResponse((r) => r.url().endsWith("/commands"));
  await page.getByRole("button", { name: "Deal first hand" }).click();
  expect((await dealt).ok()).toBeTruthy();
  await expect(page.locator(".play-workspace .hole-cards .playing-card")).toHaveCount(0);
  for (let i = 0; i < 6; i++) {
    await page.getByRole("button", { name: "Next action", exact: true }).click();
    if (await page.locator(".play-workspace .hole-cards .playing-card").count()) break;
  }
  await expect(page.locator(".play-workspace .hole-cards:has(.playing-card)")).toHaveCount(1);
  await expect(page.locator(".play-workspace .hole-cards .playing-card")).toHaveCount(1);
  for (let cards = 2; cards <= 12; cards++) {
    await page.getByRole("button", { name: "Next action", exact: true }).click();
    await expect(page.locator(".play-workspace .hole-cards .playing-card")).toHaveCount(cards);
    await expect(page.locator(".play-workspace .hole-cards:has(.playing-card)")).toHaveCount(Math.min(cards, 6));
  }
  await expect.poll(() => page.evaluate(() => (window as typeof window & { soundStarts: number }).soundStarts)).toBeGreaterThan(0);
  await page.getByLabel("Presentation speed").selectOption("brisk");
  await drain(page);
  await page.screenshot({ path: `${qa}/polished-table-desktop.png`, animations: "disabled", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverlap(page);
  await page.screenshot({ path: `${qa}/polished-table-phone.png`, animations: "disabled", fullPage: true });
  await page.reload();
  await expect(page.locator(".play-workspace .nameplate")).toHaveCount(6);
  expect(await page.evaluate(() => (window as typeof window & { soundStarts: number }).soundStarts)).toBe(0);
  await page.getByRole("button", { name: "Your account" }).click();
  await expect(page.getByRole("switch", { name: "Table sounds" })).toBeChecked();
  expect(await page.evaluate(() => (window as typeof window & { soundStarts: number }).soundStarts)).toBe(0);
  await page.getByRole("switch", { name: "Table sounds" }).uncheck();
  expect(errors).toEqual([]);
});
