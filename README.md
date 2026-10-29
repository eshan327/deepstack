# Deepstack

A deliberate, single-player, simulated-money no-limit Hold’em client. Next.js presents the table; FastAPI, Postgres, and PokerKit own the rules, ownership, and chip movement. No payments, multiplayer, solver service, or LLM calls.

## Play and review

The dark table keeps each player’s position, stack, wager, and latest action together. The action log starts closed, remembers its preference, resizes the desktop table, and becomes a drawer on phones. Fold, Call/Check, and Bet/Raise stay in consistent positions; legal sizing presets, dollar entry, and the slider describe the same raise-to total. Amount entry survives unrelated note updates. F/C/R shortcuts apply while the play workspace has focus, outside inputs and dialogs.

Default: six seats, $1/$2, $600 stacks, balanced opponents. Setup supports 2–9 seats, custom blinds, stack depth in BB, individual dollar stacks, and balanced/soft/tough fields. Opponent names are unique per new table and stable across hands, refreshes, and replay. Notes and observations follow opponent identities, never their display names or hidden strategy profiles.

Deliberate pacing allows about 1.2 seconds for folds/checks, 1.6 seconds for wagers, 1.5 seconds for streets, and 2–3 seconds for showdown and awards. Brisk and Manual are available, alongside pause and single-step. Reduced motion changes movement without speeding the game up. Hidden tabs and Review pause presentation. Betting becomes available only after the ordered event queue reaches the actual hero decision. Hero turns have no clock; the next hand always needs an explicit deal.

Review is a separate workspace with account-wide cursor pagination, session/date/stakes/bookmark filters, public hand replay, street and hero-decision jumps, notes, and text/JSON exports. Opening Review preserves the live table. Accounting stays in a secondary player-panel disclosure.

Post-hand analysis uses only the public context captured immediately before the chosen hero action. Edit opponent ranges through PokerKit notation or the range grid. Uniform compatible combinations and PokerKit evaluation target 512 accepted Monte Carlo samples within three seconds; results report actual samples, uncertainty, effective depth, position, and sizing. Ties split equity. Side-pot/all-in situations explicitly suppress a misleading full-pot call threshold. These are assumption-dependent estimates, not solver grades. Legacy hands replay normally and explicitly report missing coaching context.

## Local development

Requires Node 24+, pnpm 10.28.2, uv, Python 3.12, and Postgres.

```sh
pnpm install --frozen-lockfile
uv sync --project apps/api --frozen --python 3.12
# Put development values from .env.example in ignored .env.local.
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api uvicorn main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload
```

In another terminal:

```sh
POKER_API_ORIGIN=http://127.0.0.1:8000 pnpm dev
```

Open http://127.0.0.1:3000 and use the same hostname throughout. Python and Next’s config load the root `.env.local` without replacing injected environment values. `DATABASE_URL` is the pooled runtime URL; `DATABASE_URL_UNPOOLED` is the direct migration URL. Both are server-only. `POKER_API_ORIGIN` compiles the local API rewrite; omit it for Vercel Services.

## Accounts and Neon

Guest play works without authentication configuration. Google and email-link sign-in use managed Neon Auth through the same-origin Next proxy and custom Deepstack controls. The browser obtains a short-lived JWT; FastAPI verifies its signature, issuer, audience, expiry, and role. Invalid authenticated requests never fall back to guest access. Every session, hand, annotation, export, analysis, memory, and ledger lookup is ownership-scoped.

Sign-in transactionally links the current guest bucket to the account without moving or deleting its receipts or tables. If both identities have unfinished tables, both remain available in Review’s session selector. Sign-out rotates the anonymous cookie, so the old guest credential cannot expose account history. Profiles synchronize names, presentation preferences, and table defaults; historical event names stay as recorded. Issued JWTs remain valid until their provider expiry (approximately 15 minutes); browser sign-out does not instantly revoke a copied bearer token.

Server configuration:

- `NEON_AUTH_BASE_URL`: the current environment’s managed Auth URL, including `/neondb/auth`.
- `NEON_AUTH_COOKIE_SECRET`: a random 32+ character server secret. Use a separate production secret and store it in Vercel’s Secret type. Never expose either database credentials or the cookie secret as `NEXT_PUBLIC_*`.
- Register the exact app origins as trusted Neon domains. Keep localhost enabled only for development.
- Enable the Magic Link plugin; this project uses a 15-minute expiry.

Production Google redirect URI is `{NEON_AUTH_BASE_URL}/callback/google`. Neon’s shared Google client and SMTP are retained **for the owner’s testing by explicit request**. Before a public launch, configure an owned Google OAuth client and custom SMTP in Neon Better Auth settings, following the [production checklist](https://neon.com/docs/auth/production-checklist).

Neon setup changes made for this implementation:

- Fetched the current official Neon skill. Preserved the existing Neon and Postgres skills; installed the missing `neon-auth` skill into ignored `.agents/skills`.
- Added the project-scoped OAuth MCP entry in `.codex/config.toml`, targeting the existing development project. Existing user configuration was preserved. New MCP configuration may require restarting the agent session.
- Enabled managed Auth and 15-minute magic links on the existing development and production projects; no replacement project was provisioned.
- Added the exact loopback development origin and both existing production Vercel aliases; disabled localhost on production.
- Added local Auth environment values without replacing database configuration. Stored development/preview and separate production cookie secrets in Vercel after explicit approval. No secret is committed.
- Tested the migration in disposable empty and populated schemas, then migrated development and production to `0002`. Production retained all 16 guests, 10 sessions, 82 hands, 280 command receipts, and 89 ledger entries present at migration time. No production data was copied to another environment.
- Created disposable `example.invalid` users to verify real provider sessions, JWT ownership, browser reload, and sign-out; removed those auth users afterward.

## Architecture and API

`apps/api/deepstack/engine.py` is the narrow PokerKit 0.7.7 adapter. PokerKit owns legal actions, chip collection, side pots, and showdown. Restoration rebuilds a state from private hand parameters and deck, then replays recorded commands; it never reruns old bot decisions or unpickles objects. Version incompatibility preserves the record and fails explicitly.

`session.py` owns permanent seats, button rotation, stacks/rebuys, observations, and sanitized pre-action decision capture. `bots.py` uses position/context-specific heuristics and bounded public-information sampling. Bot policies receive only their own cards and public information.

`main.py` serializes commands with database locks, version checks, payload hashes, and durable idempotency receipts. `db.py` stores accounts, ownership buckets, sessions, memories, hands, receipts, and ledger. Private current state stays in session JSONB. Completed hands retain public presentation events and decision contexts, never future cards, mucked opponent cards, or hidden bot profiles.

Profile/claim endpoints are `/api/v1/me` and `/me/claim`; review uses `/hands`, `/hands/{id}`, `/annotation`, `/analysis`, and `/export`. `/ranges/expand` derives grid selections with PokerKit. The OpenAPI document and frontend types are checked in; regenerate with `pnpm api:types` after schema changes.

The frontend shares one ordered presentation reducer between live play and replay. Committed snapshots stay separate from presented events. Event IDs deduplicate retries; action labels retain legacy text while new events include seat, street, action, incremental wager, and raise-to total. Native DOM/CSS cards and chips keep symbols crisp, accessible, and responsive.

## Verification and CI

Use a development/test database. API tests delete only their newly created disposable ownership records; migration tests create/drop uniquely named schemas. Browser fixture seeding is local-only code, with no fixture HTTP endpoint.

```sh
pnpm api:types
pnpm test:unit
pnpm typecheck
pnpm lint
cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run python simulate.py --hands 120 --seed 20261029 --samples 64
```

For production-mode local browser checks, stop the dev server before building, and provide the API origin at **build time**:

```sh
POKER_API_ORIGIN=http://127.0.0.1:8000 pnpm build
pnpm --filter web start
pnpm exec playwright install chromium
pnpm test:e2e
```

When supplying an alternate ignored environment file, export its variables to child processes (`set -a` before sourcing). API, browser harness, and fixture seeding must target the same isolated database.

Coverage: 42 backend tests, three presentation reducer tests, and 14 browser flows. Browser checks include all eight seat counts at 1600×1000, 1440×900, 1280×720, and 390×844; expanded/collapsed logs; manual/hidden-tab pacing; reduced motion; drafted raise preservation; refresh, notes, bookmarks, replay, analysis/export; real all-in side pots and lost-response retries; and the Neon SDK session-cache/JWT regression. Real managed Auth was also exercised separately with disposable users. The seeded 120-hand simulation asserts chip/card/action integrity.

GitHub Actions use disposable Postgres 17, pinned action commits, locked installs, API contract drift checks, Python lint/format/tests/migrations/simulation, frontend types/lint/unit/build, and Chromium flows. Failure artifacts include traces, screenshots, and server logs. A second workflow audits production dependencies weekly and on dependency changes; Dependabot groups npm, uv, and Actions updates. No auto-merge or deploy credentials are granted to workflows.

The JavaScript runtime audit has no high/critical findings; one low-severity transitive `deepmerge` advisory remains in the SDK’s unused email-template UI dependency with no patched version. Python runtime audit reports no known vulnerabilities. Auth dependency overrides keep Better Auth and Zod on patched versions and are checked by the lockfile/audit workflow.

### Visual verification

Compared the accepted Play and Review concepts with actual Playwright screenshots using image inspection, plus direct in-app browser interaction. Native reference-sized desktop checks use 1600×1000; small-laptop and portrait checks cover 1280×720 and 390×844. Screenshots and failure traces go outside the repository to `/tmp/deepstack-qa` and `/tmp/deepstack-playwright`.

Inspected: (1) spacious forest table and charcoal surround, (2) ivory/sage type and tabular stack hierarchy, (3) compact name/position/stack/action clusters, (4) polished readable cards/chips/blind markers, (5) the three-button dock and connected sizing controls, and (6) the distinct Review list/replay/inspector composition. Fixed phone controls covering the hero/bottom seats, full-board overlap at nine seats, missing accessible mobile log labels, and export-menu layout shifts.

Intentional refinements from the concepts: flatter felt and lighter framing; native card/chip rendering; real legal presets and recorded amounts; compact nine-seat phone clusters; collapsed opponent range editors; functional empty/error/loading states. Above-the-fold copy stays poker-focused; additions describe actual stakes, decisions, pace, and setup rather than marketing boilerplate. The result follows the approved evolving visual direction rather than treating raster text as a rigid specification.

## Deployment and limits

Existing Vercel project: `ekhans-projects-42f8bb55/deepstack`. `vercel.json` routes `/api/v1/*` to FastAPI and everything else to Next.js using Services (currently beta). Main is the production Git branch. Apply additive migrations against the intended direct URL before deploying schema-dependent source; never migrate on function startup. Protected previews can be checked with `vercel curl` without disabling protection.

```sh
pnpm dlx vercel@latest deploy --environment preview --yes --scope ekhans-projects-42f8bb55
```

Each guest ownership bucket has one active table. Linking accounts can preserve multiple unfinished tables. Changing blinds or seat count starts a new table; top-ups, sit-outs, and replacement happen between hands. Opponents automatically rebuy after busting. Nine-seat phones omit face-down card backs and compact revealed cards; all useful action and stack information remains available.

Browser QA covers Chromium and the in-app browser, not Safari/Firefox or every device. Equity is sampling-based and depends on entered ranges; it does not model future betting or deliver side-pot EV. No tournaments, multiplayer, rake, real-money features, straddles, multiple runouts, solver integration, or LLM coaching.
