const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("pr_token");
}

export function setToken(token: string) {
  localStorage.setItem("pr_token", token);

  // Persist shop_domain from JWT payload so we can re-authenticate later.
  // This is a simple base64 decode of the payload — no crypto needed.
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    if (payload.shop_domain) {
      localStorage.setItem("pr_shop_domain", payload.shop_domain);
    }
  } catch {
    // Malformed token — ignore, shop_domain just won't be cached
  }
}

export function clearToken() {
  localStorage.removeItem("pr_token");
  // Keep pr_shop_domain intentionally — we need it to redirect to Shopify OAuth
}

export function getShopDomain(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("pr_shop_domain");
}

/**
 * Decode the JWT payload (no signature verification — just reads claims).
 */
function decodeTokenPayload(token: string): Record<string, unknown> | null {
  try {
    return JSON.parse(atob(token.split(".")[1]));
  } catch {
    return null;
  }
}

/**
 * Returns true when the token's `exp` claim is within `marginSec` seconds of
 * now (or already past).  Used for proactive refresh.
 */
function isTokenExpiringSoon(token: string, marginSec = 3600): boolean {
  const payload = decodeTokenPayload(token);
  if (!payload || typeof payload.exp !== "number") return false;
  return payload.exp - Date.now() / 1000 < marginSec;
}

// Deduplication: if a refresh is already in-flight, reuse the same promise so
// multiple concurrent 401s don't each trigger their own refresh call.
let refreshPromise: Promise<string | null> | null = null;

/**
 * Attempt to get a fresh JWT from POST /auth/refresh.
 * Returns the new token on success, or null on failure.
 */
async function tryRefreshToken(): Promise<string | null> {
  const oldToken = getToken();
  if (!oldToken) return null;

  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_URL}/api/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${oldToken}`,
        },
      });
      if (!res.ok) return null;
      const data = await res.json();
      if (data.access_token) {
        setToken(data.access_token);
        return data.access_token as string;
      }
      return null;
    } catch {
      return null;
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
  let token = getToken();

  // Proactive refresh: if the token expires within 1 hour, refresh silently
  // before making the actual request.
  if (token && isTokenExpiringSoon(token)) {
    const refreshed = await tryRefreshToken();
    if (refreshed) token = refreshed;
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let res = await fetch(`${API_URL}/api${path}`, {
    ...options,
    headers,
  });

  // Reactive refresh: on 401, try to refresh and retry *once*.
  if (res.status === 401 && typeof window !== "undefined") {
    const newToken = await tryRefreshToken();
    if (newToken) {
      // Retry the original request with the fresh token.
      headers["Authorization"] = `Bearer ${newToken}`;
      res = await fetch(`${API_URL}/api${path}`, {
        ...options,
        headers,
      });
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));

    // If still 401 after refresh attempt, the token is truly unusable
    // (tampered, >30 days old, shop deactivated, etc.) — force re-auth.
    if (res.status === 401 && typeof window !== "undefined") {
      clearToken();
      window.location.href = "/onboarding";
      throw new ApiError(res.status, "Session expired — redirecting to login");
    }

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
  return request<{ shop_id: number; shop_domain: string }>("/auth/me");
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

// Dashboard
export interface DashboardSummary {
  products_tracked: number;
  products_trend_pct: number;
  competitors_monitored: number;
  price_changes_24h: number;
  scraping_health_pct: number;
}

export interface PricePositionDistribution {
  cheapest: number;
  within_5_pct: number;
  above_average: number;
  most_expensive: number;
}

export interface AttentionProduct {
  product_id: number;
  title: string;
  our_price: number;
  competitor_name: string;
  competitor_price: number;
  diff_pct: number;
  last_changed: string | null;
}

export interface DashboardOverviewResponse {
  summary: DashboardSummary;
  price_position: PricePositionDistribution;
  attention_products: AttentionProduct[];
}

export function getDashboardOverview() {
  return request<DashboardOverviewResponse>("/dashboard/overview");
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
