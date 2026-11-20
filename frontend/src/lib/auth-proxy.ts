import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const API_BASE_URL =
  process.env.MEDIPREDICT_API_INTERNAL_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

export const SESSION_COOKIE = "medipredict_session";

type BackendTokenResponse = {
  access_token: string;
  expires_in: number;
  user: unknown;
};

export async function proxyCredentials(
  request: Request,
  endpoint: "login" | "register",
): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Please provide valid JSON." }, { status: 400 });
  }

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${API_BASE_URL}/auth/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { detail: "The MediPredict server is unavailable. Please try again shortly." },
      { status: 503 },
    );
  }

  const result = await backendResponse.json().catch(() => null) as
    | BackendTokenResponse
    | { detail?: string }
    | null;

  if (!backendResponse.ok) {
    return NextResponse.json(
      { detail: result && "detail" in result ? result.detail : "Authentication failed." },
      { status: backendResponse.status },
    );
  }

  if (!result || !("access_token" in result) || !("user" in result)) {
    return NextResponse.json({ detail: "The server returned an invalid session response." }, { status: 502 });
  }

  const response = NextResponse.json({
    user: result.user,
    expires_in: result.expires_in,
  });
  response.cookies.set(SESSION_COOKIE, result.access_token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: result.expires_in,
  });
  return response;
}

export async function getSessionUser(): Promise<{
  user: unknown;
  response?: NextResponse;
}> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  if (!token) return { user: null };

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${API_BASE_URL}/auth/me`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    return {
      user: null,
      response: NextResponse.json(
        { detail: "The MediPredict server is unavailable." },
        { status: 503 },
      ),
    };
  }

  if (!backendResponse.ok) return { user: null };
  return { user: await backendResponse.json() };
}

export async function getSessionToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get(SESSION_COOKIE)?.value ?? null;
}

export type CatalogReviewQueueItem = {
  target_type: "disease" | "symptom" | "disease_symptom";
  target_key: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string | null;
};

export type ReviewQueueFilters = {
  q?: string;
  target_type?: string;
  status?: string;
  offset?: number;
  limit?: number;
};

export async function getCatalogReviewQueue(
  filters: ReviewQueueFilters = {},
): Promise<{
  items: CatalogReviewQueueItem[];
  error: string | null;
}> {
  const token = await getSessionToken();
  if (!token) return { items: [], error: "Your session has expired. Please sign in again." };

  const params = new URLSearchParams({
    limit: String(filters.limit ?? 20),
    offset: String(filters.offset ?? 0),
  });
  if (filters.q) params.set("q", filters.q);
  if (filters.target_type && filters.target_type !== "all") {
    params.set("target_type", filters.target_type);
  }
  if (filters.status && filters.status !== "all") {
    params.append("status", filters.status);
  }

  try {
    const response = await fetch(
      `${API_BASE_URL}/catalog/review/queue?${params.toString()}`,
      {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      return {
        items: [],
        error: response.status === 403
          ? "Your account does not have catalog reviewer access."
          : "The review queue could not be loaded. Please try again.",
      };
    }
    return { items: await response.json() as CatalogReviewQueueItem[], error: null };
  } catch {
    return { items: [], error: "The MediPredict server is unavailable." };
  }
}

export type CatalogReviewEvent = {
  id: string;
  target_type: "disease" | "symptom" | "disease_symptom";
  target_key: string;
  previous_status: string;
  new_status: string;
  reason: string;
  reviewer_id: string;
  created_at: string;
};

export type ReviewHistoryFilters = {
  q?: string;
  target_type?: string;
  date_from?: string;
  date_to?: string;
};

export async function getCatalogReviewHistory(
  filters: ReviewHistoryFilters = {},
): Promise<{
  items: CatalogReviewEvent[];
  error: string | null;
}> {
  const token = await getSessionToken();
  if (!token) return { items: [], error: "Your session has expired. Please sign in again." };

  const params = new URLSearchParams({ limit: "100" });
  if (filters.q) params.set("q", filters.q);
  if (filters.target_type && filters.target_type !== "all") {
    params.set("target_type", filters.target_type);
  }
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);

  try {
    const response = await fetch(
      `${API_BASE_URL}/catalog/review/history?${params.toString()}`,
      {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      return {
        items: [],
        error: response.status === 403
          ? "Your account does not have permission to view review history."
          : "Review history could not be loaded. Please try again.",
      };
    }
    return { items: await response.json() as CatalogReviewEvent[], error: null };
  } catch {
    return { items: [], error: "The MediPredict server is unavailable." };
  }
}

export type ReviewedCatalogEntry = {
  event: CatalogReviewEvent;
  entry: {
    target_type: "disease" | "symptom" | "disease_symptom";
    target_key: string;
    name: string;
    description: string | null;
    status: string;
    created_at: string | null;
    relevance_weight: number | null;
  };
};

export async function getReviewedCatalogEntry(eventId: string): Promise<{
  data: ReviewedCatalogEntry | null;
  error: string | null;
}> {
  const token = await getSessionToken();
  if (!token) return { data: null, error: "Your session has expired. Please sign in again." };
  if (!/^[0-9a-f-]{36}$/i.test(eventId)) {
    return { data: null, error: "This review history link is invalid." };
  }

  try {
    const response = await fetch(
      `${API_BASE_URL}/catalog/review/history/${encodeURIComponent(eventId)}/entry`,
      {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      return {
        data: null,
        error: response.status === 404
          ? "This catalog entry is unavailable or is not part of your review history."
          : "The reviewed catalog entry could not be loaded.",
      };
    }
    return { data: await response.json() as ReviewedCatalogEntry, error: null };
  } catch {
    return { data: null, error: "The MediPredict server is unavailable." };
  }
}

export type GovernanceOverview = {
  accounts: Record<string, { active: number; inactive: number }>;
  catalog: {
    diseases: Record<string, number>;
    symptoms: Record<string, number>;
    disease_symptom_links: Record<string, number>;
  };
  recent_role_changes: Array<{
    id: string;
    target_user_id: string;
    previous_role: string;
    new_role: string;
    operator_identity: string;
    reason: string;
    created_at: string;
  }>;
};

export async function getGovernanceOverview(): Promise<{
  data: GovernanceOverview | null;
  error: string | null;
}> {
  const token = await getSessionToken();
  if (!token) return { data: null, error: "Your session has expired. Please sign in again." };

  try {
    const response = await fetch(`${API_BASE_URL}/admin/governance?history_limit=20`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      return {
        data: null,
        error: response.status === 403
          ? "Administrator access is required to view governance information."
          : "The governance overview could not be loaded. Please try again.",
      };
    }
    return { data: await response.json() as GovernanceOverview, error: null };
  } catch {
    return { data: null, error: "The MediPredict server is unavailable." };
  }
}

export type ReviewerAccount = {
  id: string;
  email: string;
  display_name: string | null;
};

export type ReviewerScope = {
  id: string;
  reviewer_id: string;
  reviewer_email: string;
  scope_type: "disease" | "symptom" | "disease_symptom";
  scope_key: string | null;
  granted_by: string;
  grant_reason: string;
  granted_at: string;
  revoked_by: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
};

export type ReviewerScopeEvent = {
  id: string;
  scope_id: string;
  reviewer_id: string;
  event_type: "granted" | "revoked";
  scope_type: "disease" | "symptom" | "disease_symptom";
  scope_key: string | null;
  operator_id: string;
  reason: string;
  created_at: string;
};

export async function getReviewerScopeGovernance(): Promise<{
  reviewers: ReviewerAccount[];
  scopes: ReviewerScope[];
  events: ReviewerScopeEvent[];
  error: string | null;
}> {
  const token = await getSessionToken();
  if (!token) {
    return {
      reviewers: [],
      scopes: [],
      events: [],
      error: "Your session has expired. Please sign in again.",
    };
  }

  try {
    const headers = { Authorization: `Bearer ${token}`, Accept: "application/json" };
    const [reviewersResponse, scopesResponse, eventsResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/admin/reviewers`, { headers, cache: "no-store" }),
      fetch(`${API_BASE_URL}/admin/reviewer-scopes`, { headers, cache: "no-store" }),
      fetch(`${API_BASE_URL}/admin/reviewer-scopes/history?limit=30`, { headers, cache: "no-store" }),
    ]);
    if (![reviewersResponse, scopesResponse, eventsResponse].every((response) => response.ok)) {
      return {
        reviewers: [],
        scopes: [],
        events: [],
        error: "Reviewer scope administration could not be loaded.",
      };
    }
    const [reviewers, scopes, events] = await Promise.all([
      reviewersResponse.json(),
      scopesResponse.json(),
      eventsResponse.json(),
    ]);
    return {
      reviewers: reviewers as ReviewerAccount[],
      scopes: scopes as ReviewerScope[],
      events: events as ReviewerScopeEvent[],
      error: null,
    };
  } catch {
    return {
      reviewers: [],
      scopes: [],
      events: [],
      error: "The MediPredict server is unavailable.",
    };
  }
}

export type ReviewerWorkload = {
  pending_total: number;
  is_unrestricted: boolean;
  assignments: Array<{
    scope_type: "disease" | "symptom" | "disease_symptom";
    scope_key: string | null;
    granted_at: string;
  }>;
  pending_by_type: {
    disease: number;
    symptom: number;
    disease_symptom: number;
  };
  activity: {
    total_decisions: number;
    approved_decisions: number;
    retired_decisions: number;
    decisions_last_7_days: number;
  };
};

export async function getReviewerWorkload(): Promise<{
  data: ReviewerWorkload | null;
  error: string | null;
}> {
  const token = await getSessionToken();
  if (!token) {
    return { data: null, error: "Your session has expired. Please sign in again." };
  }

  try {
    const response = await fetch(`${API_BASE_URL}/catalog/review/workload`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      return {
        data: null,
        error: response.status === 403
          ? "Your account does not have catalog reviewer access."
          : "Your review workload could not be loaded.",
      };
    }
    return { data: await response.json() as ReviewerWorkload, error: null };
  } catch {
    return { data: null, error: "The MediPredict server is unavailable." };
  }
}

