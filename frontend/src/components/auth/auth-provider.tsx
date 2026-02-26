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
  /** Whether onboarding is complete (backend or local store). */
  onboardingComplete: boolean;
  /** Shop info when authenticated. */
  shop: { id: number; domain: string } | null;
  /** Force a re-check (e.g. after completing onboarding). */
  recheck: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  status: "loading",
  onboardingComplete: false,
  shop: null,
  recheck: async () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

// ── Helpers ───────────────────────────────────────────────────────

/**
 * Check the local onboarding store (localStorage) for completion.
 * This is the source of truth for demo-mode users who have no JWT token.
 */
function isLocalOnboardingComplete(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const raw = localStorage.getItem("pr_onboarding");
    if (!raw) return false;
    const data = JSON.parse(raw);
    return data.isOnboardingComplete === true;
  } catch {
    return false;
  }
}

// ── Provider ──────────────────────────────────────────────────────

/**
 * AuthProvider resolves two independent questions on mount:
 *
 *   1. Is the user authenticated? (valid JWT — refreshing if expired)
 *   2. Has the user completed onboarding? (backend OR local store)
 *
 * The app supports two modes:
 *   - **Connected mode**: User has a JWT from Shopify OAuth. Auth is
 *     verified against the backend, onboarding status from the DB.
 *   - **Demo mode**: No JWT token. Onboarding completion is tracked
 *     purely in localStorage. Dashboard is still accessible.
 *
 * Separating auth from onboarding is critical: an expired token must NOT
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

    // ── No token path (demo mode) ──────────────────────────────
    // Users who loaded demo data have no JWT. Check local onboarding
    // store instead. This lets demo users access the dashboard without
    // being locked out by auth guards.
    if (!hasToken()) {
      const localComplete = isLocalOnboardingComplete();
      setStatus("unauthenticated");
      setOnboardingComplete(localComplete);
      setShop(null);
      return;
    }

    // ── Token path (connected mode) ────────────────────────────
    try {
      // Verify auth. The API interceptor in api.ts will automatically
      // attempt a token refresh on 401 before throwing, so by the time
      // we get here the token is either valid or truly unrecoverable.
      const me = await getAuthMe();
      setShop({ id: me.id, domain: me.shopify_domain });
      setStatus("authenticated");

      // Check onboarding status from backend (source of truth for
      // connected users). Fall back to local store if the call fails.
      try {
        const ob = await getOnboardingStatus();
        setOnboardingComplete(ob.current_step === 4);
      } catch {
        setOnboardingComplete(isLocalOnboardingComplete());
      }
    } catch (err) {
      // Token is invalid/unrecoverable (refresh also failed).
      if (err instanceof ApiError && err.status === 401) {
        clearToken();
      }
      // Even if auth failed, respect local onboarding state so users
      // who completed onboarding aren't kicked back to the wizard.
      setStatus("unauthenticated");
      setOnboardingComplete(isLocalOnboardingComplete());
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
