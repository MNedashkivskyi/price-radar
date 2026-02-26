"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  getAuthMe,
  getOnboardingStatus,
  hasToken,
  setToken,
  refreshToken,
  clearToken,
  ApiError,
} from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthState {
  /** Current auth lifecycle phase. */
  status: AuthStatus;
  /** Whether onboarding is complete (all 3 steps done on the backend). */
  onboardingComplete: boolean;
  /** Shop info when authenticated. */
  shop: { id: number; domain: string } | null;
  /** Force a re-check (e.g. after completing onboarding). */
  recheck: () => void;
}

const AuthContext = createContext<AuthState>({
  status: "loading",
  onboardingComplete: false,
  shop: null,
  recheck: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

// ── Provider ──────────────────────────────────────────────────────

/**
 * AuthProvider sits near the top of the component tree and resolves two
 * independent questions on mount:
 *
 *   1. Is the user authenticated? (valid JWT — refreshing if expired)
 *   2. Has the user completed onboarding? (backend data check)
 *
 * Separating these two concerns is critical: an expired token should NOT
 * be treated as "needs onboarding". The token is refreshed first, then
 * onboarding status is checked. This breaks the redirect loop.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [onboardingComplete, setOnboardingComplete] = useState(false);
  const [shop, setShop] = useState<{ id: number; domain: string } | null>(
    null
  );

  const check = useCallback(async () => {
    // Handle OAuth callback: extract token from URL before any auth check.
    // The Shopify OAuth flow redirects to /onboarding?token=<jwt>, so we
    // capture it here at the provider level to ensure it's available before
    // any route guard evaluates.
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const urlToken = params.get("token");
      if (urlToken) {
        setToken(urlToken);
        // Signal to step-import-products that this is an OAuth callback,
        // so it can auto-start the import. The URL will be cleaned, so
        // we use sessionStorage as a one-time signal.
        sessionStorage.setItem("pr_oauth_callback", "1");
        window.history.replaceState({}, "", window.location.pathname);
      }
    }

    // Fast path: no token at all → unauthenticated immediately.
    if (!hasToken()) {
      setStatus("unauthenticated");
      setOnboardingComplete(false);
      setShop(null);
      return;
    }

    try {
      // Step 1: Verify auth. The API interceptor in api.ts will
      // automatically attempt a token refresh on 401 before throwing,
      // so by the time we get here the token is either valid or truly
      // unrecoverable.
      const me = await getAuthMe();
      setShop({ id: me.id, domain: me.shopify_domain });
      setStatus("authenticated");

      // Step 2: Check onboarding status (independent of token state).
      try {
        const ob = await getOnboardingStatus();
        setOnboardingComplete(ob.current_step === 4);
      } catch {
        // If onboarding status fails, assume not complete to be safe.
        setOnboardingComplete(false);
      }
    } catch (err) {
      // Token is invalid/unrecoverable (refresh also failed).
      if (err instanceof ApiError && err.status === 401) {
        clearToken();
      }
      setStatus("unauthenticated");
      setOnboardingComplete(false);
      setShop(null);
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  return (
    <AuthContext.Provider
      value={{ status, onboardingComplete, shop, recheck: check }}
    >
      {children}
    </AuthContext.Provider>
  );
}
