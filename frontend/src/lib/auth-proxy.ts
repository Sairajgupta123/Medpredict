import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { hasSameRequestOrigin } from "@/lib/request-origin";

export const API_BASE_URL =
  process.env.MEDIPREDICT_API_INTERNAL_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

export const SESSION_COOKIE = "medipredict_session";

function privateJson(body: unknown, init: ResponseInit = {}): NextResponse {
  const headers = new Headers(init.headers);
  headers.set("Cache-Control", "private, no-store, max-age=0");
  headers.set("Pragma", "no-cache");
  return NextResponse.json(body, { ...init, headers });
}

type BackendTokenResponse = {
  access_token: string;
  expires_in: number;
  user: unknown;
};

export async function proxyCredentials(
  request: Request,
  endpoint: "login" | "register",
): Promise<NextResponse> {
  if (!hasSameRequestOrigin(request)) {
    return privateJson({ detail: "Invalid request origin." }, { status: 403 });
  }

  const maxCredentialBodyBytes = 32 * 1024;
  const declaredLength = request.headers.get("content-length");
  if (
    declaredLength !== null &&
    (!/^\\d+$/.test(declaredLength) || Number(declaredLength) > maxCredentialBodyBytes)
  ) {
    return privateJson({ detail: "Authentication request is too large." }, { status: 413 });
  }

  let payload: unknown;
  const reader = request.body?.getReader();
  if (!reader) {
    return privateJson({ detail: "Please provide valid JSON." }, { status: 400 });
  }

  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > maxCredentialBodyBytes) {
        await reader.cancel();
        return privateJson({ detail: "Authentication request is too large." }, { status: 413 });
      }
      chunks.push(value);
    }
  } catch {
    await reader.cancel().catch(() => undefined);
    return privateJson({ detail: "Please provide valid JSON." }, { status: 400 });
  }

  try {
    const body = new Uint8Array(totalBytes);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
    payload = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return privateJson({ detail: "Please provide valid JSON." }, { status: 400 });
  }

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${API_BASE_URL}/auth/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    return privateJson(
      { detail: "The MediPredict server is unavailable. Please try again shortly." },
      { status: 503 },
    );
  }

  const result = await backendResponse.json().catch(() => null) as
    | BackendTokenResponse
    | { detail?: string }
    | null;

  if (!backendResponse.ok) {
    return privateJson(
      { detail: result && "detail" in result ? result.detail : "Authentication failed." },
      { status: backendResponse.status },
    );
  }

  if (
    !result ||
    !("access_token" in result) ||
    typeof result.access_token !== "string" ||
    result.access_token.length < 20 ||
    result.access_token.length > 8192 ||
    !("expires_in" in result) ||
    typeof result.expires_in !== "number" ||
    !Number.isSafeInteger(result.expires_in) ||
    result.expires_in < 1 ||
    result.expires_in > 60 * 60 * 24 * 30 ||
    !("user" in result) ||
    !result.user ||
    typeof result.user !== "object" ||
    Array.isArray(result.user)
  ) {
    return privateJson(
      { detail: "The server returned an invalid session response." },
      { status: 502 },
    );
  }

  const response = privateJson({
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
      signal: AbortSignal.timeout(8_000),
    });
  } catch {
    return {
      user: null,
      response: privateJson(
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
        cache: "no-store", signal: AbortSignal.timeout(8_000),
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
        cache: "no-store", signal: AbortSignal.timeout(8_000),
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
        cache: "no-store", signal: AbortSignal.timeout(8_000),
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
      cache: "no-store", signal: AbortSignal.timeout(8_000),
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
      fetch(`${API_BASE_URL}/admin/reviewers`, { headers, cache: "no-store", signal: AbortSignal.timeout(8_000) }),
      fetch(`${API_BASE_URL}/admin/reviewer-scopes`, { headers, cache: "no-store", signal: AbortSignal.timeout(8_000) }),
      fetch(`${API_BASE_URL}/admin/reviewer-scopes/history?limit=30`, { headers, cache: "no-store", signal: AbortSignal.timeout(8_000) }),
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
      cache: "no-store", signal: AbortSignal.timeout(8_000),
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



export type PendingCatalogEntry = {
  entry: {
    target_type: "disease" | "symptom" | "disease_symptom";
    target_key: string;
    name: string;
    description: string | null;
    status: string;
    is_active: boolean;
    created_at: string | null;
    reviewed_by: string | null;
    reviewed_at: string | null;
    related_entries: Array<{
      target_type: "disease" | "symptom";
      target_key: string;
      name: string;
      status: string;
    }>;
    relevance_weight: number | null;
  };
  evidence: {
    references: CatalogReferenceItem[];
    reference_support: "not_implemented" | "available";
    message: string;
  };
};

export type CatalogReferenceItem = {
  id: string;
  reference_id: string;
  title: string;
  publisher: string;
  url: string;
  evidence_type: string;
  version: string;
  published_on: string | null;
  accessed_on: string;
  review_status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  next_review_due: string | null;
  link_reason: string;
  linked_by: string;
  linked_at: string;
};

export type ReviewableMedicalReference = Omit<
  CatalogReferenceItem,
  "id" | "reference_id" | "link_reason" | "linked_by" | "linked_at"
> & { id: string };

export async function getReviewableMedicalReferences(q = ""): Promise<{
  items: ReviewableMedicalReference[];
  error: string | null;
}> {
  const token = await getSessionToken();
  if (!token) return { items: [], error: "Your session has expired. Please sign in again." };
  const params = new URLSearchParams({ limit: "50" });
  if (q.trim()) params.set("q", q.trim());
  try {
    const response = await fetch(
      `${API_BASE_URL}/catalog/review/references?${params.toString()}`,
      { headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }, cache: "no-store", signal: AbortSignal.timeout(8_000) },
    );
    if (!response.ok) {
      return { items: [], error: "The medical source registry could not be loaded." };
    }
    return { items: await response.json() as ReviewableMedicalReference[], error: null };
  } catch {
    return { items: [], error: "The MediPredict server is unavailable." };
  }
}

export async function attachCatalogReference(
  targetType: string, targetKey: string, referenceId: string, reason: string,
): Promise<{ error: string | null }> {
  const token = await getSessionToken();
  if (!token) return { error: "Your session has expired. Please sign in again." };
  try {
    const response = await fetch(`${API_BASE_URL}/catalog/review/queue/entry/references`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        target_type: targetType, target_key: targetKey, reference_id: referenceId, reason,
      }),
      cache: "no-store", signal: AbortSignal.timeout(8_000),
    });
    if (response.ok) return { error: null };
    if (response.status === 409) return { error: "This source is already attached." };
    if (response.status === 403) return { error: "Your reviewer scope does not permit this action." };
    return { error: "The source could not be attached. Check the source and reason." };
  } catch {
    return { error: "The MediPredict server is unavailable." };
  }
}

export async function removeCatalogReference(
  linkId: string, reason: string,
): Promise<{ error: string | null }> {
  const token = await getSessionToken();
  if (!token) return { error: "Your session has expired. Please sign in again." };
  try {
    const response = await fetch(
      `${API_BASE_URL}/catalog/review/queue/entry/references/${encodeURIComponent(linkId)}/remove`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ reason }),
        cache: "no-store", signal: AbortSignal.timeout(8_000),
      },
    );
    if (response.ok) return { error: null };
    if (response.status === 403) return { error: "Your reviewer scope does not permit this action." };
    return { error: "The source link could not be removed." };
  } catch {
    return { error: "The MediPredict server is unavailable." };
  }
}

export async function getPendingCatalogEntry(
  targetType: string,
  targetKey: string,
): Promise<{ data: PendingCatalogEntry | null; error: string | null }> {
  const token = await getSessionToken();
  if (!token) return { data: null, error: "Your session has expired. Please sign in again." };
  if (
    !["disease", "symptom", "disease_symptom"].includes(targetType) ||
    !targetKey ||
    targetKey.length > 200
  ) {
    return { data: null, error: "This catalog inspection link is invalid." };
  }

  const params = new URLSearchParams({ target_type: targetType, target_key: targetKey });
  try {
    const response = await fetch(
      `${API_BASE_URL}/catalog/review/queue/entry?${params.toString()}`,
      {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store", signal: AbortSignal.timeout(8_000),
      },
    );
    if (!response.ok) {
      return {
        data: null,
        error: response.status === 404
          ? "This pending catalog entry is unavailable."
          : response.status === 403
            ? "Your account is not assigned to inspect this catalog scope."
            : "The catalog entry could not be loaded. Please try again.",
      };
    }
    return { data: await response.json() as PendingCatalogEntry, error: null };
  } catch {
    return { data: null, error: "The MediPredict server is unavailable." };
  }
}
