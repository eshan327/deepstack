import type { components } from "./api.generated";

export type Snapshot = components["schemas"]["Snapshot"];
export type TableView = components["schemas"]["TableView"];
export type SeatView = components["schemas"]["SeatView"];
export type Action = components["schemas"]["Action-Input"];
export type Command = components["schemas"]["Command"];
export type CommandResult = components["schemas"]["CommandResult"];
export type PublicEvent = components["schemas"]["PublicEvent"];
export type TableConfig = components["schemas"]["TableConfig-Input"];
export type HandSummary = components["schemas"]["HandSummary"];
export type HandList = components["schemas"]["HandList"];
export type Replay = components["schemas"]["Replay"];
export type SessionList = components["schemas"]["SessionList"];
export type LedgerList = components["schemas"]["LedgerList"];
export type Profile = components["schemas"]["Profile"];
export type Preferences = components["schemas"]["Preferences-Output"];
export type ReviewHands = components["schemas"]["ReviewHands"];
export type AnalysisResult = components["schemas"]["AnalysisResult"];

let accountToken: (() => Promise<string | null>) | null = null;
export function setAccountToken(
  provider: (() => Promise<string | null>) | null,
) {
  accountToken = provider;
}

export async function requestHeaders(): Promise<Record<string, string>> {
  const token = accountToken ? await accountToken() : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const headers = await requestHeaders();
  const init: RequestInit = {
    credentials: "same-origin",
    cache: "no-store",
    headers,
  };
  if (body !== undefined) {
    init.method = "POST";
    init.headers = { ...headers, "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, init);
  } catch {
    throw new ApiError(0, "Connection lost. Retry the action.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      response.status,
      typeof data.detail === "string"
        ? data.detail
        : "The table is temporarily unavailable. Retry shortly.",
    );
  }
  return data as T;
}

export function money(cents: number, bb?: number) {
  if (bb)
    return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(cents / bb)} BB`;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: cents % 100 ? 2 : 0,
  }).format(cents / 100);
}

export const defaults: TableConfig = {
  players: 6,
  small_blind: 100,
  big_blind: 200,
  starting_stack: 60000,
  field: "balanced",
};
