const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("pr_token");
}

export function setToken(token: string) {
  localStorage.setItem("pr_token", token);
}

export function clearToken() {
  localStorage.removeItem("pr_token");
}

/**
 * Check if the stored JWT token exists. Does NOT validate expiry —
 * that's the backend's job. This is only used for fast "do we have
 * a token at all?" checks in route guards.
 */
export function hasToken(): boolean {
  return getToken() !== null;
}

// ── Token refresh with deduplication ─────────────────────────────
// If multiple requests hit 401 at the same time, we only send one
// refresh request. All waiters share the same promise.
let refreshPromise: Promise<boolean> | null = null;

/**
 * Attempt to refresh the JWT token using the /auth/refresh endpoint.
 * The backend accepts expired tokens (signature-only check) so this
 * works even after the 24h window expires — breaking the redirect loop.
 *
 * Returns true if refresh succeeded, false otherwise.
 */
export async function refreshToken(): Promise<boolean> {
  // Deduplicate concurrent refresh attempts
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const token = getToken();
    if (!token) return false;

    try {
      const res = await fetch(`${API_URL}/api/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) return false;

      const data = await res.json();
      if (data.access_token) {
        setToken(data.access_token);
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}/api${path}`, {
    ...options,
    headers,
  });

  // ── 401 interceptor: attempt token refresh once, then retry ────
  // This prevents expired-token errors from bubbling up as auth failures
  // and triggering incorrect redirects to /onboarding.
  if (res.status === 401 && token && path !== "/auth/refresh") {
    const refreshed = await refreshToken();
    if (refreshed) {
      // Retry the original request with the new token
      const retryHeaders: Record<string, string> = {
        ...headers,
        Authorization: `Bearer ${getToken()!}`,
      };
      const retryRes = await fetch(`${API_URL}/api${path}`, {
        ...options,
        headers: retryHeaders,
      });
      if (!retryRes.ok) {
        const body = await retryRes.json().catch(() => ({}));
        throw new ApiError(retryRes.status, body.detail || retryRes.statusText);
      }
      return retryRes.json();
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || res.statusText);
  }

  return res.json();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Auth
export function getAuthMe() {
  return request<{
    id: number;
    shopify_domain: string;
    plan: string;
    status: string;
    created_at: string;
  }>("/auth/me");
}

// Products
export function importProducts() {
  return request<{
    status: string;
    job_id?: string;
    product_count?: number;
    stats?: { created: number; updated: number; skipped: number };
  }>("/products/import", { method: "POST" });
}

export function getImportStatus(jobId: string) {
  return request<{
    job_id: string;
    status: string;
    progress?: number;
    message?: string;
    stats?: { created: number; updated: number; skipped: number };
    result?: { created: number; updated: number; skipped: number };
  }>(`/products/import/status/${jobId}`);
}

export interface ListProductsParams {
  skip?: number;
  limit?: number;
  search?: string;
  tag?: string;
  sort_by?: "title" | "our_price" | "created_at" | "competitors_tracked";
  sort_order?: "asc" | "desc";
}

export function listProducts(params: ListProductsParams = {}) {
  const { skip = 0, limit = 25, search, tag, sort_by, sort_order } = params;
  const qs = new URLSearchParams();
  qs.set("skip", String(skip));
  qs.set("limit", String(limit));
  if (search) qs.set("search", search);
  if (tag) qs.set("tag", tag);
  if (sort_by) qs.set("sort_by", sort_by);
  if (sort_order) qs.set("sort_order", sort_order);
  return request<{
    products: Product[];
    total: number;
    skip: number;
    limit: number;
    all_tags: string[];
  }>(`/products?${qs.toString()}`);
}

// Competitors
export function createCompetitor(data: {
  name: string;
  domain: string;
  logo_url?: string;
}) {
  return request<Competitor>("/competitors", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function listCompetitors() {
  return request<Competitor[]>("/competitors");
}

export function detectCompetitor(url: string) {
  return request<{ name: string; domain: string; logo_url?: string }>(
    `/competitors/detect?url=${encodeURIComponent(url)}`
  );
}

// Competitor product mappings (under /competitors/products)
export function createMapping(data: {
  product_id: number;
  competitor_id: number;
  url: string;
}) {
  return request<CompetitorMapping>("/competitors/products", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function bulkCreateMappings(
  mappings: { product_id: number; competitor_id: number; url: string }[]
) {
  // Backend expects CSV data as string
  const csvHeader = "product_id,competitor_url";
  const csvRows = mappings.map((m) => `${m.product_id},${m.url}`);
  const csvData = [csvHeader, ...csvRows].join("\n");

  return request<{
    success_count: number;
    error_count: number;
    errors: { row: number; error: string }[];
    created_competitors: string[];
  }>("/competitors/products/bulk", {
    method: "POST",
    body: JSON.stringify({ csv_data: csvData }),
  });
}

// Onboarding
export function getOnboardingStatus() {
  return request<OnboardingStatus>("/onboarding/status");
}

// Types
export interface Product {
  id: number;
  shopify_product_id: string;
  title: string;
  handle: string;
  image_url: string | null;
  our_price: number;
  currency: string;
  tags: string | null;
  variants_count: number;
  competitors_tracked: number;
  created_at: string;
  updated_at: string;
}

export interface Competitor {
  id: number;
  shop_id: number;
  name: string;
  domain: string;
  logo_url: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CompetitorMapping {
  id: number;
  product_id: number;
  competitor_id: number;
  url: string;
  selector_config: Record<string, unknown>;
  status: string;
  last_scraped_at: string | null;
  last_success_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OnboardingStatus {
  current_step: number;
  steps: {
    step: number;
    completed: boolean;
    completed_at: string | null;
  }[];
}

export function getShopifyInstallUrl(shopDomain: string): string {
  return `${API_URL}/api/shopify/install?shop=${encodeURIComponent(shopDomain)}`;
}
