"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-provider";

/**
 * Loading spinner shown while auth status is being resolved.
 * Prevents flash-of-wrong-content and premature redirects.
 */
function AuthLoading() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    </div>
  );
}

// ── RequireAuth ───────────────────────────────────────────────────

/**
 * Guard for routes that require authentication AND completed onboarding
 * (e.g. /dashboard/*).
 *
 * Redirect logic:
 *   - No token / auth failed → /onboarding  (need to connect store)
 *   - Authenticated but onboarding incomplete → /onboarding
 *   - Authenticated + onboarding complete → render children
 *
 * The key fix: we wait for the auth provider to finish its check
 * (which includes token refresh) BEFORE making any redirect decision.
 * This eliminates the race condition that caused the infinite loop.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status, onboardingComplete } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return; // Wait for auth resolution

    if (status === "unauthenticated") {
      router.replace("/onboarding");
      return;
    }

    if (status === "authenticated" && !onboardingComplete) {
      router.replace("/onboarding");
    }
  }, [status, onboardingComplete, router]);

  if (status === "loading") return <AuthLoading />;
  if (status === "unauthenticated") return <AuthLoading />;
  if (status === "authenticated" && !onboardingComplete) return <AuthLoading />;

  return <>{children}</>;
}

// ── RequireOnboarding ─────────────────────────────────────────────

/**
 * Guard for the /onboarding route.
 *
 * Redirect logic:
 *   - Authenticated + onboarding already complete → /dashboard
 *     (prevents returning users from seeing onboarding again)
 *   - Otherwise → render children (show onboarding wizard)
 *
 * This guard ensures /onboarding is ONLY shown to users who genuinely
 * need it, regardless of token state.
 */
export function RequireOnboarding({ children }: { children: React.ReactNode }) {
  const { status, onboardingComplete } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return;

    // Already onboarded → go straight to dashboard.
    if (status === "authenticated" && onboardingComplete) {
      router.replace("/dashboard");
    }
  }, [status, onboardingComplete, router]);

  if (status === "loading") return <AuthLoading />;

  // If already onboarded, show loading while redirect happens
  if (status === "authenticated" && onboardingComplete) return <AuthLoading />;

  return <>{children}</>;
}
