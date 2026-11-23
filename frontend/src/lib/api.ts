const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init.headers,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new ApiError(body?.detail ?? "The request could not be completed.", response.status);
  }

  return response.json() as Promise<T>;
}

export type HealthResponse = {
  status: string;
  app_name?: string;
  version?: string;
};

export type CatalogItem = {
  id: string;
  code: string;
  name: string;
  description: string | null;
};

export type CatalogListResponse = {
  items: CatalogItem[];
  total: number;
  limit: number;
  offset: number;
};

export type ResearchModelCapability = {
  status: "not_configured" | "invalid_configuration" | "configured_not_loaded";
  configured: boolean;
  loaded: false;
  inference_enabled: false;
};

export type ResearchModelStatusResponse = {
  skin_image: ResearchModelCapability;
  symptom_text: ResearchModelCapability;
  research_only: true;
  clinical_diagnosis_enabled: false;
};
